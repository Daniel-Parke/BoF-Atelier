"""Two bounded, private checkpoint slots per game. Ordinary cards remain independent."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from . import memory_card
from .local_store import StoreError, atomic_bytes, canonical_bytes, plain_path

KINDS = ("quick", "suspend")
MAX_STATE = 64 * 1024**2
MAX_HEADER = 4096
FORMAT = 1


@dataclass(frozen=True)
class Checkpoint:
    state: bytes
    cards: dict[int, bytes]


def card_identity(cards: dict[int, bytes]) -> dict[str, str]:
    return {str(slot): hashlib.sha256(data).hexdigest() for slot, data in cards.items()}


def path_for(root: Path, game: str, kind: str) -> Path:
    if game not in ("bof3", "bof4") or kind not in KINDS:
        raise StoreError("Choose a checkpoint for this game.")
    return plain_path(root / "lab/checkpoints" / game / (kind + ".checkpoint"))


def file_stamp(path: Path) -> tuple[int, int, int] | None:
    try:
        info = plain_path(path).stat()
    except FileNotFoundError:
        return None
    return info.st_mtime_ns, info.st_ctime_ns, info.st_size


def capture(root: Path, game: str, kind: str, source: Path, before: tuple | None,
            identity: dict, anchor: dict[str, str], cards: dict[int, bytes]) -> bool:
    stamp = file_stamp(source)
    if stamp is None or stamp == before:
        return False
    if not 0 < stamp[2] <= MAX_STATE:
        raise StoreError("The runtime checkpoint exceeds the supported file size.")
    with plain_path(source).open("rb") as file:
        state = file.read(MAX_STATE + 1)
    if len(state) != stamp[2] or file_stamp(source) != stamp:
        raise StoreError("The runtime checkpoint changed during capture.")
    header = canonical_bytes({
        "format": FORMAT, "game": game, "kind": kind,
        "created": datetime.now(timezone.utc).isoformat(),
        "identity": identity, "ordinary": anchor, "cards": card_identity(cards),
        "bytes": len(state), "sha256": hashlib.sha256(state).hexdigest(),
    })
    if len(header) >= MAX_HEADER:
        raise StoreError("The checkpoint receipt exceeds the supported size.")
    atomic_bytes(path_for(root, game, kind), b"\n".join((header, state)) +
                 b"".join(data for _, data in sorted(cards.items())))
    return True


def load(root: Path, game: str, kind: str, identity: dict,
         ordinary: dict[str, str]) -> Checkpoint:
    with path_for(root, game, kind).open("rb") as file:
        line = file.readline(MAX_HEADER)
        if not line.endswith(b"\n"):
            raise StoreError("The checkpoint receipt is damaged.")
        header = json.loads(line)
        if not isinstance(header, dict) or (header.get("format"), header.get("game"),
                                           header.get("kind")) != (FORMAT, game, kind):
            raise StoreError("The checkpoint format is unsupported.")
        if header.get("identity") != identity or header.get("ordinary") != ordinary:
            raise StoreError("The checkpoint differs from the current runtime or campaign.")
        size = header.get("bytes")
        if type(size) is not int or not 0 < size <= MAX_STATE:
            raise StoreError("The checkpoint size is invalid.")
        state = file.read(size)
        if len(state) != size or hashlib.sha256(state).hexdigest() != header.get("sha256"):
            raise StoreError("The checkpoint failed verification.")
        hashes = header.get("cards")
        if not isinstance(hashes, dict) or not hashes.keys() <= {"1", "2"}:
            raise StoreError("The checkpoint card receipt is invalid.")
        cards = {}
        for slot, digest in sorted(hashes.items()):
            data = file.read(memory_card.CARD_SIZE)
            if hashlib.sha256(data).hexdigest() != digest or memory_card.inspect_card(data)["warnings"]:
                raise StoreError("The checkpoint's copied card failed verification.")
            cards[int(slot)] = data
        if file.read(1):
            raise StoreError("The checkpoint contains unexpected data.")
    return Checkpoint(state, cards)
