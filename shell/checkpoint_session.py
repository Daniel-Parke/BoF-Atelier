"""Check compatibility and isolate the writable cards for managed Lab resumes."""
from __future__ import annotations

from pathlib import Path, PureWindowsPath
from uuid import uuid4

from tools import checkpoints, managed_cards, runtime_reference_play
from tools import runtime_setup as runtime
from tools.existing_runtime import reuse_installation
from tools.local_store import atomic_bytes, fingerprint, plain_path


def identity(root: Path, game: str, record: dict, mode: str, lock: dict) -> dict:
    if mode == "stock":
        directory = runtime._installation(root, "lab", "duckstation")
        settings = runtime._effective_game_settings(directory, game)
        sections = ("Console", "CPU", "CDROM", "GPU", "Hacks", "BIOS", "PCDrive")
        critical = {section: dict(settings[section]) for section in sections if section in settings}
        critical["ApplyGameSettings"] = settings.getboolean("Main", "ApplyGameSettings", fallback=True)
        executable = runtime._component("duckstation", "lab")["package"]["executable"]
        binary = runtime._digest(plain_path(directory / executable))
        compatibility = fingerprint(critical)
    else:
        directory = runtime._installation(root, "lab", runtime_reference_play.BACKEND)
        binary = runtime._digest(plain_path(directory / "pcsx-redux.exe"))
        # Change the contract when the reviewed reference emulation flags change.
        compatibility = "reference-win-v1:full-boot,softgpu,2mb,dynarec"
    return {
        "content": record["fingerprint"], "profile": lock["profile"], "runtime": lock["runtime"],
        "firmware": lock["firmware"], "backend": lock["backend"], "binary": binary,
        "cue": runtime._digest(plain_path(Path(record["cue"]))), "configuration": compatibility,
    }


def launch_stock_copy(root: Path, game: str, cue: Path, checkpoint: checkpoints.Checkpoint,
                      controls: dict[str, list[str]], gameplay: dict[str, str] | None,
                      preferences: dict):
    branch = plain_path(root / "lab/q")
    with runtime.reserve_idle_channel(root, "lab"):
        base = runtime._installation(root, "lab", "duckstation")
        status = runtime.game_launch_status(root, game, "lab")
        firmware = runtime._selected_firmware(root, "lab", base)
        target = Path(reuse_installation(branch, Path(status["executable"]), "lab")["data_root"])
        with runtime.reserve_idle_channel(branch, "lab"):
            source = plain_path(base / "bios" / firmware["filename"])
            runtime._bind_idle(branch, "lab", firmware | {"path": str(source)})
            settings = runtime._effective_game_settings(base, game)
            game_settings = PureWindowsPath(settings.get("Folders", "GameSettings", fallback="gamesettings"))
            serial_ini = managed_cards.SERIALS[game] + ".ini"
            override = runtime._path(base, *game_settings.parts, serial_ini)
            if override.exists() and settings.getboolean("Main", "ApplyGameSettings", fallback=True):
                # Preserve core overrides, but let the copy own both memory-card ports.
                import configparser
                from io import StringIO
                copy = configparser.ConfigParser(strict=False, interpolation=None)
                copy.optionxform = str
                copy.read_string(override.read_text(encoding="utf-8-sig"))
                copy.remove_section("MemoryCards")
                buffer = StringIO()
                copy.write(buffer)
                atomic_bytes(runtime._path(target, *game_settings.parts, serial_ini), buffer.getvalue().encode())
            else:
                previous = runtime._path(target, *game_settings.parts, serial_ini)
                if previous.is_file():
                    # Clear a prior copy's override without touching the source profile.
                    atomic_bytes(previous, b"")
            local = runtime._path(target, "settings.ini")
            atomic_bytes(local, runtime._path(base, "settings.ini").read_bytes())
            cards_directory = "cards/" + uuid4().hex[:12]
            runtime._rewrite_settings(local, {"MemoryCards": {
                "Directory": cards_directory, "Card1Type": "Shared", "Card2Type": "Shared",
                "Card1Path": "slot-1.mcd", "Card2Path": "slot-2.mcd",
            }})
            cards = managed_cards.duckstation_paths(branch, "lab", game, cue)
            for slot, data in checkpoint.cards.items():
                atomic_bytes(cards[slot], data)
            atomic_bytes(branch / "resume.sav", checkpoint.state)
        process = runtime.launch_game(
            branch, game, cue, "lab", library_root=root, gameplay=gameplay,
            checkpoint_controls=controls, resume=True, **preferences,
        )
    process.atelier_cards = cards
    return process


def capture(root: Path, operation: dict) -> list[str]:
    capture_info = operation.get("checkpoint")
    if not capture_info or not capture_info["files"]:
        return []
    game = operation["game"]
    current = managed_cards.read_cards(game, operation["paths"])
    anchor = capture_info["anchor"]
    if anchor is None:
        anchor = checkpoints.card_identity(current.slots) if current.title else {}
    return [
        kind for kind, (source, before) in capture_info["files"].items()
        if checkpoints.capture(root, game, kind, source, before, capture_info["identity"], anchor, current.slots)
    ]
