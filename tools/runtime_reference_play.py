"""Open the private, interactive PCSX-Redux reference Lab with fresh disposable cards."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys

from . import runtime_linux, runtime_setup as runtimes
from .checkpoints import Checkpoint


BACKEND = "pcsx-redux-cli"


def _is_linux() -> bool:
    return sys.platform.startswith('linux')

# Explicit local qualification only. These fixed frames contain the emulated game
# surface. The public Player path leaves captures off and accepts no external Lua.
WITNESS = """
local ffi = require('ffi')
local frame = 0
atelierReferenceWitness = PCSX.Events.createEventListener('GPU::Vsync', function()
    frame = frame + 1
    if frame == 900 or frame == 2250 or frame == 3200 then
        local screen = PCSX.GPU.takeScreenShot()
        local width, height, size = screen.width, screen.height, screen.data.size
        if width > 0 and height > 0 and size <= 4194304 then
            local file = assert(io.open(string.format('frame-%05d-%dx%d-%d.raw', frame, width, height, size), 'wb'))
            file:write(ffi.string(screen.data.data, size))
            file:close()
        end
    end
end)
"""


def reference_status(private_root: Path, game: str = "bof4") -> dict:
    linux=_is_linux()
    entry=runtime_linux.component() if linux else runtimes._component(BACKEND,'lab')
    result = {
        "backend": runtime_linux.BACKEND if linux else BACKEND,
        "channel": "lab",
        "game": game,
        "version": entry["version"],
        "ready": False,
        "reason": "",
    }
    if game not in ("bof3", "bof4"):
        result["reason"] = "Select a supported game revision."
        return result
    try:
        if linux:
            runtime_linux.verify(private_root,full=False)
            result.update(ready=True,reason='Open an isolated Ubuntu reference session with its own memory cards.')
            return result
        runtimes._check_windows()
        directory = runtimes._installation(private_root, "lab", BACKEND)
        firmware = runtimes._catalogue()["openbios-psx-rom"]["member"]
        if not (
            runtimes._path(directory, ".atelier-runtime.json").is_file()
            and runtimes._matches(
                runtimes._path(directory, entry["package"]["executable"]),
                entry["package"]["executable_sha256"],
            )
            and runtimes._matches(
                runtimes._path(directory, firmware["name"]), firmware["sha256"]
            )
        ):
            raise runtimes.RuntimeSetupError(
                "Prepare the verified PCSX-Redux console build and its replacement firmware in Lab."
            )
        result.update(
            ready=True,
            reason="Open an isolated reference session with its own memory cards.",
        )
    except (OSError, runtimes.RuntimeSetupError) as error:
        result["reason"] = str(error)
    return result


def reading_campaign(receipt: dict, session_id: str) -> str:
    """Older sessions retain the original Guide scope. Isolate a malformed newer tag."""
    lineage = receipt.get("guide_campaign", "")
    if lineage == "":
        return ""
    return lineage if isinstance(lineage, str) and re.fullmatch(r"\d{8}T\d{12}Z", lineage) else session_id


def launch_reference_game(
    private_root: Path,
    game: str,
    cue: Path,
    *,
    card_evidence: str | None = None,
    from_session: str | None = None,
    capture_witness: bool = False,
    gameplay: dict[str, str] | None = None,
    restored_branch: str | None = None,
    card_seed: dict[int, bytes] | None = None,
    checkpoint_keys: dict[str, str] | None = None,
    checkpoint: Checkpoint | None = None,
) -> subprocess.Popen:
    """Start the native window. Each invocation creates a new private Lab session."""
    status = reference_status(private_root, game)
    if not status["ready"]:
        raise runtimes.RuntimeSetupError(status["reason"])
    cue = runtimes._verified_cue(private_root, game, cue)
    linux=_is_linux()
    if checkpoint_keys is not None and linux:
        raise runtimes.RuntimeSetupError("Managed checkpoints are qualified for the Windows reference build.")
    if checkpoint is not None:
        if checkpoint_keys is None or card_seed is not None or not restored_branch:
            raise runtimes.RuntimeSetupError("Resume requires a separate Lab card branch.")
        card_seed = checkpoint.cards or None
    if linux:
        runtime_linux.verify(private_root)
        binary_root=runtime_linux.directory(private_root)
        executable=binary_root/runtime_linux.component()['package']['executable']
        process_identity=runtime_linux.process_identity
    else:
        runtimes._verify_installation(private_root,'lab',BACKEND)
        binary_root=runtimes._installation(private_root,'lab',BACKEND)
        executable=binary_root/'pcsx-redux.exe'
        process_identity=runtimes._process_identity
    firmware = runtimes._catalogue()["openbios-psx-rom"]["member"]
    previous_cards = []
    if restored_branch is not None and not re.fullmatch(r"[0-9a-f]{32}", restored_branch):
        raise runtimes.RuntimeSetupError("Select a saved Lab branch.")
    if card_seed is not None:
        from .memory_card import inspect_card
        if (not restored_branch or card_evidence or from_session or not card_seed
                or any(slot not in (1, 2) or inspect_card(body)["warnings"] for slot, body in card_seed.items())):
            raise runtimes.RuntimeSetupError("The restored memory cards are invalid.")
    if card_evidence and from_session:
        raise runtimes.RuntimeSetupError(
            "Choose either a previous reference session or a verified evidence card pair."
        )
    previous = card_evidence or from_session
    guide_campaign = ""
    if previous:
        if not re.fullmatch(r"\d{8}T\d{12}Z", previous):
            raise runtimes.RuntimeSetupError(
                "Select a completed private Lab card evidence run for this game."
            )
        parent = runtimes._path(
            private_root,
            "lab",
            "evidence" if card_evidence else "reference-play",
            game,
            previous,
        )
        proof = json.loads(
            runtimes._path(
                parent, "probe.json" if card_evidence else "session.json"
            ).read_text(encoding="utf-8")
        )
        if (
            proof.get("game") != game
            or proof.get("backend") != status['backend']
            or proof.get("version") != status["version"]
            or (card_evidence and proof.get("exit_code") != 0)
            or proof.get("firmware_sha256") != firmware["sha256"]
            or proof.get("cue_sha256") != runtimes._digest(cue)
        ):
            raise runtimes.RuntimeSetupError(
                "The selected evidence record differs from this game or reference runtime."
            )
        if from_session:
            guide_campaign = reading_campaign(proof, from_session)
            if proof.get("restored_branch") != restored_branch:
                raise runtimes.RuntimeSetupError("The previous session belongs to another campaign.")
            pid = proof.get("pid")
            if type(pid) is not int or "created" not in proof:
                raise runtimes.RuntimeSetupError(
                    "The selected session has no recorded process identity."
                )
            observed = process_identity(pid)
            if observed and observed[1]==proof['created']:
                raise runtimes.RuntimeSetupError(
                    "Close the previous reference session before copying its cards."
                )
        fingerprints = {
            item["name"]: item["sha256"] for item in proof.get("disposable_cards", [])
        }
        for name in ("disposable1.mcd", "disposable2.mcd"):
            source = runtimes._path(parent, name)
            if not source.is_file() or source.stat().st_size != 131072:
                raise runtimes.RuntimeSetupError(
                    "The selected evidence cards require verification."
                )
            expected = runtimes._digest(source)
            if card_evidence and fingerprints.get(name) != expected:
                raise runtimes.RuntimeSetupError(
                    "The selected evidence card differs from its receipt."
                )
            previous_cards.append((source, expected))
    session_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    session = runtimes._path(private_root, "lab", "reference-play", game, session_id)
    session.mkdir(parents=True, exist_ok=False)
    if not from_session and not restored_branch and any(
            other != session and re.fullmatch(r"\d{8}T\d{12}Z", other.name) for other in session.parent.iterdir()):
        # A new blank campaign gets its own bookmarks. First play keeps any pre-game marks.
        guide_campaign = session_id
    if gameplay is not None and not linux:
        from .runtime_input import redux_port
        runtimes._atomic_json(session / "pcsx.json", {"pads": [redux_port(gameplay)]})
    cards = [session / f"disposable{index}.mcd" for index in (1, 2)]
    for slot, data in (card_seed or {}).items():
        cards[slot - 1].write_bytes(data)
    for (source, expected), target in zip(previous_cards, cards):
        shutil.copyfile(source, target)
        if runtimes._digest(target) != expected:
            raise runtimes.RuntimeSetupError(
                "Verification of the cloned Lab memory card failed."
            )
    args = [
        str(executable),
        *(['--appimage-extract-and-run'] if linux else []),
        "-portable",
        str(session),
        "-noupdate",
        "-no-fastboot",
        "-no-gdb",
        "-no-webserver",
        "-no-pcdrv",
        "-no-viewports",
        "-softgpu",
        "-2mb",
        "-dynarec",
        "-bios",
        str(binary_root / firmware["name"]),
        "-iso",
        str(cue),
        "-memcard1",
        str(cards[0]),
        "-memcard2",
        str(cards[1]),
        "-logfile",
        str(session / "runtime.log"),
        "-run",
    ]
    # Derive the optional visit observer only from the checked game and backend.
    # Rewindable checkpoints, untracked imports and unrelated branches have no
    # prior world history. Each writable session gets a distinct witness token.
    visit_token = secrets.token_hex(16) if game == "bof4" and not linux else None
    # The pinned console subsystem still creates its native GUI. Skip the separate
    # GUI exe and universal wrapper, which initialise the graphical crash reporter.
    metadata = {
        "game": game,
        "backend": status['backend'],
        "version": status["version"],
        "firmware_sha256": firmware["sha256"],
        "cue_sha256": runtimes._digest(cue),
        "cards_from": card_evidence,
        "previous_session": from_session,
        "session_id": session_id,
        "guide_campaign": guide_campaign,
        "host_pid": os.getpid(),
        "capture_witness": capture_witness,
        "restored_branch": restored_branch,
    }
    if visit_token is not None:
        metadata["guide_visit_token"] = visit_token
    runtimes._atomic_json(session / "session.json", metadata)
    script = None
    if checkpoint_keys is not None or visit_token is not None:
        from . import redux_checkpoints
        visit_seed = None
        if visit_token is not None and checkpoint is None:
            from . import guide_visits
            if from_session:
                visit_seed = guide_visits.inherit_saved_context(parent, session, cards, visit_token)
            elif restored_branch and card_seed:
                visit_seed = guide_visits.inherit_restored_context(private_root, restored_branch, session, cards, visit_token)
        script = redux_checkpoints.prepare(
            session, checkpoint_keys, checkpoint, visit_token=visit_token,
            new_campaign=not (card_evidence or from_session or restored_branch or checkpoint), visit_seed=visit_seed,
        )
    if capture_witness:
        from .local_store import atomic_bytes
        # Redux receives a single source-owned entry point even when the private
        # GPU witness and the normal controls run in the same reference session.
        body = script.read_bytes() if script is not None else b""
        script = session / "capture-witness.lua"
        atomic_bytes(script, body + WITNESS.encode("ascii"))
    if script is not None:
        args.extend(["-dofile", str(script)])
    attached_cards = dict(enumerate(cards, 1))
    recorder = None
    if visit_token is not None:
        from .guide_visits import VisitRecorder
        # Establish file identity and the inherited card pair before firmware can write.
        recorder = VisitRecorder(session, visit_token, attached_cards)
    process = subprocess.Popen(
        args,
        cwd=session,
        # The Player owns guide navigation while this managed Lab window is
        # in the background. Other processes keep their own SDL hints.
        env=None if linux else os.environ | {"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS": "0"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        identity = process_identity(process.pid)
        if identity is None:
            raise runtimes.RuntimeSetupError(
                "The reference runtime exited before its window could open."
            )
        runtimes._atomic_json(
            session / "session.json",
            metadata | {"pid": process.pid, "created": identity[1]},
        )
    except Exception:
        runtimes._stop_unregistered_runtime(process)
        raise
    process.atelier_cards = attached_cards
    process.atelier_visit_recorder = recorder
    process.atelier_guide_campaign = guide_campaign
    process.atelier_guide_visits = session / "guide-visits.json" if visit_token is not None else None
    process.atelier_guide_visit_token = visit_token
    process.atelier_checkpoints = ({kind: (session / (kind + ".state"), None)
                                    for kind in ("quick", "suspend")} if checkpoint_keys else {})
    process.atelier_resume_witness = session / "atelier-resumed" if checkpoint is not None else None
    return process


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, default=runtimes.DEFAULT_PRIVATE)
    parser.add_argument("--game", choices=("bof3", "bof4"), required=True)
    parser.add_argument("--cue", type=Path, required=True)
    parser.add_argument(
        "--card-evidence",
        help="Optional completed Lab run. Only verified copies of its two ordinary cards are used.",
    )
    parser.add_argument(
        "--from-session",
        help="Resume from copies of a previous closed reference session’s ordinary cards.",
    )
    parser.add_argument(
        "--capture-witness",
        action="store_true",
        help="Save three private game frames for an explicit local qualification run.",
    )
    args = parser.parse_args()
    try:
        process = launch_reference_game(
            args.private_root,
            args.game,
            args.cue,
            card_evidence=args.card_evidence,
            from_session=args.from_session,
            capture_witness=args.capture_witness,
        )
        raise SystemExit(process.wait())
    except (OSError, ValueError, runtimes.RuntimeSetupError) as error:
        parser.exit(1, str(error) + "\n")
