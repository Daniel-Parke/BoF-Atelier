"""Identify supported runtime card slots and inspect raw cards without writing them."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
import re
from unicodedata import normalize

from .local_store import StoreError, plain_path
from . import memory_card, runtime_setup as runtime

SERIALS = {"bof3": "SLUS-00422", "bof4": "SLUS-01324"}
SAVE_TITLES = {"bof3": "Breath of Fire III (USA)", "bof4": "Breath of Fire IV (USA)"}


@dataclass(frozen=True)
class CardData:
    slots: dict[int, bytes]
    title: str


def read_cards(game: str, paths: dict[int, Path]) -> CardData:
    data = {}
    titles = []
    for slot, path in sorted(paths.items()):
        path = plain_path(path)
        if not path.exists():
            continue
        with path.open("rb") as stream:
            body = stream.read(memory_card.CARD_SIZE + 1)
        result = memory_card.inspect_card(body)
        if result["warnings"]:
            raise StoreError("An active memory card failed verification. Earlier backups are available.")
        data[slot] = body
        titles.extend(save["title"] or SAVE_TITLES[game] for save in result["slots"]
                      if save["game"] == game and save["has_save_header"])
    return CardData(data, normalize("NFKC", titles[0]).strip() if titles else "")


def duckstation_paths(root: Path, channel: str, game: str, cue: Path) -> dict[int, Path]:
    directory = runtime._installation(root, channel, "duckstation")
    settings = runtime._effective_game_settings(directory, game)
    if settings.get("ControllerPorts", "MultitapMode", fallback="Disabled") != "Disabled":
        return {}
    relative = PureWindowsPath(settings.get("MemoryCards", "Directory", fallback="memcards"))
    folder = runtime._path(directory, *relative.parts)
    paths = {}
    for slot in (1, 2):
        card_type = settings.get("MemoryCards", f"Card{slot}Type", fallback="PerGameTitle" if slot == 1 else "None")
        if card_type in {"None", "NonPersistent"}:
            continue
        if card_type == "Shared":
            custom = PureWindowsPath(settings.get("MemoryCards", f"Card{slot}Path", fallback=""))
            name = custom.parts or (f"shared_card_{slot}.mcd",)
        else:
            title = {"PerGame": SERIALS[game], "PerGameTitle": SAVE_TITLES[game],
                     "PerGameFileTitle": cue.stem}.get(card_type)
            if not title or re.search(r'[<>:"/\\|?*\x00-\x1f]', title):
                return {}
            name = (f"{title}_{slot}.mcd",)
        paths[slot] = runtime._path(folder, *name)
    return paths


def slot_paths(folder: Path) -> dict[int, Path]:
    return {slot: plain_path(folder / f"disposable{slot}.mcd") for slot in (1, 2)}


def restored_cards(branch: Path, receipt: dict) -> CardData:
    """Accept known port filenames, or a single unambiguous legacy card."""
    paths = {}
    files = receipt["files"]
    if not 1 <= len(files) <= 2 or any(file["kind"] != "card" for file in files):
        raise StoreError("Select a backup containing one or two ordinary memory cards.")
    for file in files:
        path = runtime._path(branch, *file["path"].split("/"))
        if not runtime._matches(path, file["sha256"]):
            raise StoreError("The restored card differs from its backup.")
        match = re.search(r"(?:^slot-|^disposable|_)([12])\.[^.]+$", path.name, re.IGNORECASE)
        if not match and len(files) != 1:
            raise StoreError("The memory-card ports in this backup are ambiguous.")
        slot = int(match[1]) if match else 1
        if slot in paths:
            raise StoreError("The backup contains two cards for the same port.")
        paths[slot] = path
    return read_cards(receipt["game"], paths)

