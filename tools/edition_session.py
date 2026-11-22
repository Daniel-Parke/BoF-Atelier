"""Open III's reviewed integer-scaling operation in its own persistent Windows Lab branch."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from . import editions, runtime_setup as runtime
from .existing_runtime import reuse_installation
from .local_store import atomic_bytes, canonical_bytes, fingerprint, plain_path


def prepare_integer_lab(private_root: Path, game: str, cue: Path) -> dict:
    if game != "bof3":
        raise runtime.RuntimeSetupError("The rendered integer-scaling pack is qualified for the III Lab only.")
    private_root = plain_path(private_root)
    verified_cue = runtime._verified_cue(private_root, game, cue)
    with runtime.reserve_idle_channel(private_root, "lab"):
        source = runtime._installation(private_root, "lab", "duckstation")
        status = runtime.game_launch_status(private_root, game, "lab")
        if not status["can_launch"]:
            raise runtime.RuntimeSetupError(status["reason"])
        firmware = runtime._selected_firmware(private_root, "lab", source)
        runtime._review_game_settings(source, game, firmware["filename"])
        raw = plain_path(source / "settings.ini").read_bytes()
        scaling, _ = editions._scaling(raw.decode("utf-8-sig"))
        game_receipt = json.loads(plain_path(private_root / "games" / game / "import-receipt.json").read_bytes())
        base = {"game": game, "game_sha256": game_receipt["content_fingerprint"],
                "firmware_sha256": firmware["sha256"], "runtime_sha256": runtime._digest(Path(status["executable"])),
                "settings_sha256": hashlib.sha256(raw).hexdigest(), "scaling": scaling,
                "backend": "duckstation-external", "version": status["version"]}
        pack = editions.integer_pack(game, base["game_sha256"], scaling)
        identifier = fingerprint(editions.resolve(base, [pack], "personal"))
        # Keep stock resource filenames inside Windows' legacy path limit. Verify
        # the complete identity before reading or writing a shortened branch.
        branch = plain_path(private_root / "lab/runs" / identifier[:16])
        branch.mkdir(parents=True, exist_ok=True)
        identity = plain_path(branch / "identity")
        try:
            with identity.open("x", encoding="ascii") as handle:
                handle.write(identifier)
        except FileExistsError:
            if identity.read_text(encoding="ascii") != identifier:
                raise runtime.RuntimeSetupError("The existing branch does not match the full edition lock.")
        store = editions.EditionStore(branch)
        activated = store.activate(base, [pack], raw, "personal")
        if activated["id"] != identifier:
            raise runtime.RuntimeSetupError("The resolved edition identity changed.")
        installation = reuse_installation(branch, Path(status["executable"]), "lab")
        target = Path(installation["data_root"])
        with runtime.reserve_idle_channel(branch, "lab"):
            source_bios = plain_path(source / "bios" / firmware["filename"])
            runtime._bind_idle(branch, "lab", {**firmware, "path": str(source_bios)})
            settings = plain_path(Path(activated["path"]) / "settings.ini").read_bytes()
            atomic_bytes(target / "settings.ini", settings)
            runtime._selected_firmware(branch, "lab", target)
            atomic_bytes(branch / "edition-lock.json", canonical_bytes(activated["lock"]))
    return {"branch": str(branch), "cue": str(verified_cue), "id": identifier, "data_root": str(target),
            "settings_sha256": hashlib.sha256(settings).hexdigest()}


def launch_integer_lab(private_root: Path, game: str, cue: Path) -> subprocess.Popen:
    prepared = prepare_integer_lab(private_root, game, cue)
    return runtime.launch_game(Path(prepared["branch"]), game, Path(prepared["cue"]), "lab",
                               library_root=private_root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cue", type=Path)
    parser.add_argument("--private", type=Path, default=Path("private"))
    parser.add_argument("--launch", action="store_true")
    args = parser.parse_args()
    try:
        if args.launch:
            raise SystemExit(launch_integer_lab(args.private, "bof3", args.cue).wait())
        print(json.dumps(prepare_integer_lab(args.private, "bof3", args.cue), indent=2))
    except (OSError, ValueError, runtime.RuntimeSetupError) as error:
        parser.exit(2, f"{error}\n")
