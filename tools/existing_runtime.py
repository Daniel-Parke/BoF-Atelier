"""Reuse a selected stock Windows installation in a separate, version-pinned Atelier channel."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from . import runtime_setup as rt
from .local_store import member_path, plain_path


INVENTORY = Path(__file__).resolve().parents[1] / "research/duckstation-windows-files.json"


def reuse_installation(private_root: Path, executable: Path, channel: str = "lab") -> dict:
    rt._check_windows()
    entry = rt._component("duckstation", channel)
    package = entry["package"]
    executable = plain_path(executable)
    if (executable.name.casefold() != package["executable"].casefold()
            or not executable.is_file() or rt._digest(executable) != package["executable_sha256"]):
        raise rt.RuntimeSetupError("Select the stock Windows x64 executable for " + entry["version"] + ".")
    source = executable.parent
    destination = rt._installation(private_root, channel, "duckstation")
    inventory = json.loads(INVENTORY.read_bytes())
    if (inventory["release_id"] != package["release_id"] or inventory["package_sha256"] != package["sha256"]
            or package["executable"] not in inventory["files"]):
        raise rt.RuntimeSetupError("The installed-file catalogue differs from the locked release.")
    files = [member_path(name) for name in inventory["files"]]
    if len(set(s.casefold() for s in files)) != len(files):
        raise rt.RuntimeSetupError("The installed-file catalogue contains duplicate names.")
    if destination != source and destination.is_relative_to(source):
        raise rt.RuntimeSetupError("Choose a library outside the selected installation.")
    with rt.reserve_idle_channel(private_root, channel):
        destination.parent.mkdir(parents=True, exist_ok=True)
        inputs = []
        total = 0
        for name in files:
            path = plain_path(source / name)
            if not path.is_file():
                raise rt.RuntimeSetupError("The selected runtime is missing a required program file: " + name)
            size = path.stat().st_size
            total += size
            if total > 16 * package["bytes"]:
                raise rt.RuntimeSetupError("Selected program files exceed the reviewed installation budget.")
            inputs.append((name, path, size))
        if not destination.exists() and shutil.disk_usage(destination.parent).free < total + 1024**2:
            raise rt.RuntimeSetupError("Insufficient disk space for the isolated runtime.")
        with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".reuse-") as tmp:
            stage = Path(tmp) / "stock"
            present = destination.exists()
            hashes = {}
            for name, path, expected_bytes in inputs:
                if present:
                    hashes[name] = rt._digest(path)
                    continue
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                actual_bytes = 0
                with path.open("rb") as src, target.open("xb") as out:
                    while chunk := src.read(1024**2):
                        actual_bytes += len(chunk)
                        if actual_bytes > expected_bytes:
                            raise rt.RuntimeSetupError("A selected file changed during reuse.")
                        out.write(chunk)
                        digest.update(chunk)
                if actual_bytes != expected_bytes:
                    raise rt.RuntimeSetupError("A selected program file was truncated during reuse.")
                hashes[name] = digest.hexdigest()
            if rt._manifest_digest(hashes) != package["files_sha256"]:
                raise rt.RuntimeSetupError("The selected installation differs from the complete pinned stock build.")
            if not present:
                (stage / "portable.txt").touch()
                rt._atomic_json(stage / ".atelier-runtime.json",
                                {"version": entry["version"], "backend": "duckstation", "channel": channel,
                                 "sha256": package["sha256"], "files": hashes, "method": "selected-local-installation",
                                 "verification": "Matched the complete locked program-file set."})
                stage.rename(destination)
        rt._verify_installation(private_root, channel, "duckstation")
    return {**rt._installation_info(private_root, channel, "duckstation"), "verified_files": len(files)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--private", type=Path, default=Path("private"))
    parser.add_argument("--channel", choices=("play", "lab"), default="lab")
    args = parser.parse_args()
    try:
        print(json.dumps(reuse_installation(args.private, args.executable, args.channel), indent=2))
    except (OSError, ValueError, rt.RuntimeSetupError) as error:
        parser.exit(2, f"{error}\n")
