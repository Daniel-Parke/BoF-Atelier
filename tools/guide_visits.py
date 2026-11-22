"""Read witnessed IV arrivals and bind an ordinary save to its own Lab session."""

from __future__ import annotations

from functools import reduce
from hashlib import sha256
import json
from operator import xor
from pathlib import Path
import re
import time

from . import guide_story, memory_card
from .local_store import atomic_bytes, canonical_bytes, plain_path


NODES = {index: (x, z, page) for (_, x, z), (index, _, page) in guide_story.IV_WORLD_VISITS.items()}
# Active story on the actual first-route saves. The disc's road unlock bank can differ.
# The paired ordinary saves and the corresponding quest are in verification/IV-WORLD-VISITS.md.
FIRST_STORY = {
    61: 2,
    4: 3,
    6: 1,
    7: 1,
    10: 5,
    30: 6,
    35: 9,
    42: 10,
    44: 10,
    91: 11,
    96: 12,
    50: 13,
    84: 14,
    80: 15,
    69: 17,
}
SAVED = "guide-saved-visit.json"
INVALID = "guide-saved-visit.invalid"
LIVE = "guide-visits.json"
UNKNOWN_CARD = object()


class AmbiguousCards(ValueError):
    """The runtime cannot identify one ordinary campaign file on the attached cards."""


def _read(path: Path) -> dict:
    with plain_path(path).open("rb") as reader:
        data = reader.read(8193)
    if len(data) > 8192:
        raise ValueError("Oversized visit receipt")
    obj = json.loads(data)
    if not isinstance(obj, dict):
        raise ValueError("Invalid visit receipt")
    return obj


def _scope(folder: Path) -> dict:
    receipt = _read(folder / "session.json")
    token = receipt.get("guide_visit_token")
    if (
        receipt.get("game") != "bof4"
        or receipt.get("session_id") != folder.name
        or not isinstance(token, str)
        or not re.fullmatch("[0-9a-f]{32}", token)
    ):
        raise ValueError("Unknown IV session")
    return {
        "session": folder.name,
        "token": token,
        "campaign": receipt.get("guide_campaign", ""),
        "restored": receipt.get("restored_branch"),
    }


def _valid(state: dict, token: str) -> bool:
    limits = {
        "node": (-1, 107),
        "frame": (0, 2**53),
        "epoch": (0, 2**53),
        "scenario": (0, 255),
        "map": (0, 65535),
        "section": (0, 255),
        "progress": (0, 0xFFFFFFFF),
    }
    if (
        not isinstance(state, dict)
        or type(state.get("version")) is not int
        or state["version"] != 1
        or state.get("token") != token
        or type(state.get("trusted")) is not bool
        or any(
            type(state.get(k)) is not int or not low <= state[k] <= high for k, (low, high) in limits.items()
        )
        or not isinstance(state.get("seen"), str)
        or not re.fullmatch("[0-9a-f]{28}", state["seen"])
        or not isinstance(state.get("tile"), list)
        or len(state["tile"]) != 2
        or any(type(coord) is not int or not -1 <= coord <= 65535 for coord in state["tile"])
    ):
        return False
    node = state["node"]
    if node < 0:
        return state.get("visit") == "away"
    return (
        state.get("visit") in ("arrived", "baseline", "returned")
        and state["map"] == 0x805
        and state["section"] == 0
        and bool(bytes.fromhex(state["seen"])[node // 8] & (1 << (node % 8)))
        and (node not in NODES or tuple(state["tile"]) == NODES[node][:2])
    )


def _context(state: dict, label: str) -> dict:
    if state["trusted"] and state["visit"] == "arrived" and FIRST_STORY.get(state["node"]) == state["scenario"]:
        context = {"game": "bof4", "place": NODES[state["node"]][2], "source": label}
        if state["node"] == 7:
            context["floorId"] = 0x0400
        return context
    return {}


def _observation(folder: Path, token: str) -> dict:
    blocked = plain_path(folder / "guide-visits.blocked")
    if blocked.exists():
        raise ValueError("Game observation interrupted")
    path = plain_path(folder / LIVE)
    state = _read(path)
    if blocked.exists() or not _valid(state, token) or not -1 <= time.time() - path.stat().st_mtime <= 15:
        raise ValueError("No current game observation")
    # Heartbeats establish freshness. Only the transition frame identifies a visit.
    state["frame"] = state.get("arrival", state["frame"])
    if type(state["frame"]) is not int or state["frame"] < 0:
        raise ValueError("Invalid visit transition")
    state.pop("sequence", None)
    return state


def live_context(folder: Path, token: str) -> dict | None:
    """None permits the existing diary rules. A known world position owns its manual fallback."""
    try:
        state = _observation(folder, token)
        if state["map"] == 0x805 and state["node"] < 0:
            return {}
        if state["node"] >= 0:
            if state["node"] == 0 and state["scenario"] == 2:
                return None  # North Desert retains its independently qualified opening diary rule.
            context = _context(state, "First visit")
            if context:
                context["visitKey"] = f"{token}/{state['epoch']}/{state['frame']}"
            return context
    except (OSError, ValueError, KeyError, RecursionError):
        return {}  # A missing current position cannot justify opening an older saved page.
    return None


def _stamps(paths: dict[int, Path]) -> tuple:
    if set(paths) != {1, 2}:
        raise ValueError("Unknown card attachment")
    result = []
    for port in (1, 2):
        try:
            result.append(guide_story._card_stamp(paths[port]))
        except FileNotFoundError:
            result.append(None)
    return tuple(result)


def _card_images(paths: dict[int, Path]) -> list[bytes | None]:
    before = _stamps(paths)
    images = []
    for port in (1, 2):
        if before[port - 1] is None:
            images.append(None)
            continue
        with plain_path(paths[port]).open("rb") as reader:
            data = reader.read(memory_card.CARD_SIZE + 1)
        images.append(data)
    if _stamps(paths) != before:
        raise ValueError("Card changed during inspection")
    return images


def _card_snapshot(paths: dict[int, Path]) -> tuple[list[str], bytes | None, tuple[int, str] | None]:
    before = _stamps(paths)
    slots = []
    hashes = []
    for port, data in enumerate(_card_images(paths), 1):
        if data is None:
            hashes.append("")
            continue
        info = memory_card.inspect_card(data)
        if (
            info["warnings"]
            or len(data) != memory_card.CARD_SIZE
            or any(data[i * memory_card.FRAME] not in {0x51, 0xA0, 0xA1, 0xA2, 0xA3} for i in range(1, 16))
        ):
            raise ValueError("Invalid card")
        hashes.append(sha256(data).hexdigest())
        for entry in info["slots"]:
            if (
                entry["game"] != "bof4"
                or len(entry["blocks"]) != 1
                or entry["bytes"] != memory_card.BLOCK
            ):
                raise AmbiguousCards("Ambiguous card")
            start = entry["blocks"][0] * memory_card.BLOCK
            slots.append(((port, entry["filename"]), data[start : start + memory_card.BLOCK]))
    if len(slots) > 1:
        raise AmbiguousCards("Ambiguous ordinary save")
    if _stamps(paths) != before:
        raise ValueError("Card changed during inspection")
    if not slots:
        return hashes, None, None
    slot, block = slots[0]
    if (
        block[:2] != b"SC"
        or block[2] not in (0x11, 0x12, 0x13)
        or block[3] != 1
        or block[0x184F] != reduce(xor, block[:0x184F])
    ):
        raise ValueError("Invalid ordinary save checksum")
    return hashes, block, slot


def _cards(paths: dict[int, Path]) -> tuple[list[str], bytes | None]:
    hashes, block, _ = _card_snapshot(paths)
    return hashes, block


def _matches(block: bytes, state: dict) -> bool:
    stage, section = block[0xFF4:0xFF6]
    area = int.from_bytes(block[0xFF6:0xFF8], "little")
    if (area, section, stage) != (state["map"], state["section"], state["scenario"]) or stage >= 23:
        return False
    word = 0x1004 + stage * 4
    if int.from_bytes(block[word : word + 4], "little") != state["progress"]:
        return False
    if area != 0x805:
        return state["node"] == -1
    pointer = int.from_bytes(block[0xF5C:0xF60], "little")
    tile = [int.from_bytes(block[i : i + 2], "little") for i in (0xFF8, 0xFFA)]
    return (
        state["node"] >= 0
        and tile == state["tile"]
        and pointer == guide_story.IV_NODE_TABLE + guide_story.IV_NODE_BYTES * state["node"]
    )


class VisitRecorder:
    """A write must occur between observations of the same uninterrupted visit."""

    def __init__(self, folder: Path, token: str, paths: dict[int, Path]):
        self.folder = folder
        self.token = token
        self.paths = paths
        self.previous = None
        self.stamps = None
        self.payload = UNKNOWN_CARD
        self.boot_hashes = None
        self.slot = None
        self.detached = False
        self.retirement_pending = False
        # Only the launcher's verified inherited receipt can start this window.
        # A naked import has no receipt, even when its game block is identical.
        if (folder / SAVED).is_file():
            bound = _bound(folder, paths)
            if bound and bound["scope"]["token"] == token:
                try:
                    stamps = _stamps(paths)
                    images = _card_images(paths)
                    originals = [sha256(data).hexdigest() if data is not None else "" for data in images]
                    if originals == bound["cards"] and _stamps(paths) == stamps:
                        frame = memory_card.FRAME
                        self.boot_hashes = [
                            {original, sha256(data[:63 * frame] + data[:frame] + data[64 * frame:]).hexdigest()}
                            if data is not None else {""}
                            for data, original in zip(images, originals)
                        ]
                        self.stamps = stamps
                except (OSError, ValueError):
                    pass

    def _detach(self) -> None:
        self.detached = True
        self.retirement_pending = True
        self._invalidate()
        self.retirement_pending = False

    def _invalidate(self) -> None:
        receipt = self.folder / SAVED
        if receipt.is_file():
            # A reader can hold the old receipt open on Windows. Block its use
            # before trying to replace it, including after a process interruption.
            marker = plain_path(self.folder / INVALID)
            if not marker.exists():
                atomic_bytes(marker, b"")
            atomic_bytes(receipt, b"{}")

    def sample(self) -> None:
        try:
            if self.detached:
                if self.retirement_pending:
                    self._detach()
                return
            try:
                stamps = _stamps(self.paths)
            except ValueError:
                self._detach()
                return
            if self.stamps and any(
                old and (not new or old[:2] != new[:2]) for old, new in zip(self.stamps, stamps)
            ):
                self._detach()
                return
            try:
                state = _observation(self.folder, self.token)
            except (ValueError, KeyError, RecursionError, FileNotFoundError):
                state = None
            if self.boot_hashes is not None:
                if stamps != self.stamps:
                    # OpenBIOS mirrors frame 0 into reserved frame 63 while loading.
                    # Leave the original receipt pending; _bound still requires both
                    # ORIGINAL full-card hashes before reading or inheriting it.
                    images = _card_images(self.paths)
                    hashes = [sha256(data).hexdigest() if data is not None else "" for data in images]
                    if _stamps(self.paths) != stamps:
                        return
                    if any(h not in allowed for h, allowed in zip(hashes, self.boot_hashes)):
                        self._detach()
                        return
                    self.stamps = stamps
                if state is None:
                    return
                self.boot_hashes = None
            if self.stamps is not None and stamps != self.stamps:
                # A return saved within the same game minute can reproduce the original bytes.
                # A changed card attachment cannot retain a claim from a different visit.
                receipt = self.folder / SAVED
                if receipt.is_file():
                    saved = _read(receipt)
                    if saved and saved.get("state") != state:
                        self._invalidate()
            if not state or not state["trusted"]:
                self.stamps, self.payload, self.previous = stamps, UNKNOWN_CARD, None
                return
            previous = self.previous
            if self.stamps == stamps and previous is not None:
                self.previous = state
                return
            try:
                hashes, block, slot = _card_snapshot(self.paths)
            except AmbiguousCards:
                self._detach()
                return
            except ValueError:
                # Retry even if Windows next exposes the same write timestamp.
                if previous != state:
                    self.payload = UNKNOWN_CARD
                    self.previous = None
                return
            old_stamps, prior_block = self.stamps, self.payload
            if self.slot is not None and slot != self.slot:
                self._detach()
                return
            if (
                old_stamps is not None
                and prior_block is not UNKNOWN_CARD
                and block
                and prior_block != block
                and previous == state
                and _matches(block, state)
            ):
                if _stamps(self.paths) != stamps:
                    return
                try:
                    if _observation(self.folder, self.token) != state:
                        return
                except (ValueError, KeyError, RecursionError):
                    return
                scope = _scope(self.folder)
                if scope["token"] != self.token:
                    return
                atomic_bytes(
                    self.folder / SAVED,
                    canonical_bytes({"scope": scope, "cards": hashes, "state": state}),
                )
                plain_path(self.folder / INVALID).unlink(missing_ok=True)
            # Commit the in-memory baseline only after the receipt write succeeds.
            # An interrupted read or sharing violation can retry the same write.
            self.stamps, self.payload, self.slot, self.previous = stamps, block, slot, state
        except OSError:
            return
        except (ValueError, KeyError, RecursionError):
            self.previous = None


def _bound(folder: Path, paths: dict[int, Path]) -> dict | None:
    try:
        invalid = plain_path(folder / INVALID)
        if invalid.exists():
            return None
        scope = _scope(folder)
        receipt = _read(folder / SAVED)
        state = receipt["state"]
        if (
            receipt["scope"] != scope
            or not isinstance(state, dict)
            or not _valid(state, scope["token"])
            or not state["trusted"]
        ):
            return None
        hashes, block = _cards(paths)
        if block and hashes == receipt["cards"] and _matches(block, state) and not invalid.exists():
            return {
                **receipt,
                "saved_tile": [int.from_bytes(block[i : i + 2], "little") for i in (0xFF8, 0xFFA)],
            }
    except (OSError, ValueError, KeyError, RecursionError):
        pass
    return None


def saved_context(folder: Path, paths: dict[int, Path]) -> dict:
    receipt = _bound(folder, paths)
    return _context(receipt["state"], "Last in-game save") if receipt else {}


def inherit_saved_context(parent: Path, session: Path, cards: list[Path], token: str) -> dict | None:
    """The launch has already verified the parent and copied its two cards."""
    receipt = _bound(parent, dict(enumerate(cards, 1)))
    if not receipt:
        return None
    state = receipt["state"] | {"token": token}
    scope = receipt["scope"] | {"session": session.name, "token": token}
    atomic_bytes(session / SAVED, canonical_bytes({"scope": scope, "cards": receipt["cards"], "state": state}))
    return state | {"first": state["visit"] == "arrived", "tile": receipt["saved_tile"]}


def preserve_restore_point(root: Path, point: dict, recorder: VisitRecorder) -> None:
    """Only local, closed-game backups carry observer provenance into a fork."""
    receipt = _bound(recorder.folder, recorder.paths)
    if (
        not receipt
        or not re.fullmatch("[0-9a-f]{32}", point["id"])
        or point["game"] != "bof4"
        or point["channel"] != "lab"
    ):
        return
    captured = {item["path"]: item["sha256"] for item in point["files"]}
    if any(captured.get(f"slot-{port}.mcd", "") != h for port, h in enumerate(receipt["cards"], 1)):
        return
    atomic_bytes(
        root / "lab/field-guide/restore-visits" / (point["id"] + ".json"),
        canonical_bytes({"point": point["id"], "lock": point["edition_lock"], "receipt": receipt}),
    )


def inherit_restored_context(
    root: Path, branch: str, session: Path, cards: list[Path], token: str
) -> dict | None:
    try:
        if not re.fullmatch("[0-9a-f]{32}", branch):
            return None
        fork = _read(root / "lab/restored/bof4" / branch / "branch.json")
        point = fork["parent"]
        if fork["id"] != branch or fork["game"] != "bof4" or not re.fullmatch("[0-9a-f]{32}", point):
            return None
        saved = _read(root / "lab/field-guide/restore-visits" / (point + ".json"))
        receipt = saved["receipt"]
        hashes, block = _cards(dict(enumerate(cards, 1)))
        state = receipt["state"]
        if (
            saved["point"] != point
            or saved["lock"] != fork["source_lock"]
            or fork.get("active_lock") != saved["lock"]
            or not block
            or hashes != receipt["cards"]
            or not _valid(state, receipt["scope"]["token"])
            or not state["trusted"]
            or not _matches(block, state)
        ):
            return None
        state = state | {"token": token}
        scope = {"session": session.name, "token": token, "campaign": "", "restored": branch}
        atomic_bytes(session / SAVED, canonical_bytes({"scope": scope, "cards": hashes, "state": state}))
        return state | {
            "first": state["visit"] == "arrived",
            "tile": [int.from_bytes(block[i : i + 2], "little") for i in (0xFF8, 0xFFA)],
        }
    except (OSError, KeyError, TypeError, ValueError, RecursionError):
        return None
