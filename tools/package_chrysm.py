"""Build the portable Chrysm skill from its approved public plates and recipes."""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
SLUG = "patter-art-chrysm"
SOURCE = ROOT / "design/skills" / SLUG
OUTPUT = ROOT / "private/skill-deliveries/patter_art_chrysm.zip"
TEXT_FILES = ("SKILL.md", "agents/openai.yaml", "references/prompts.md", "references/plates.json")


def contents() -> dict[str, bytes]:
    files = {name: (SOURCE / name).read_bytes() for name in TEXT_FILES}
    pins = json.loads(files["references/plates.json"])["plates"]
    css = (ROOT / "design/field-guide/plates.css").read_text(encoding="ascii")
    plates = re.findall(r"--art-([a-z]+):\s*url\('data:image/webp;base64,([^']+)'\)", css)
    if {name for name, _ in plates} != set(pins) or len(plates) != len(pins):
        raise ValueError("The approved plate set differs from the art manifest.")
    for name, encoded in plates:
        raw = base64.b64decode(encoded, validate=True)
        if raw[8:12] != b"WEBP" or sha256(raw).hexdigest() != pins[name]["sha256"]:
            raise ValueError(f"The approved {name} plate failed verification.")
        files[f"references/{name}.webp"] = raw
    return files


def package(destination: Path) -> None:
    files = contents()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        staged = Path(directory) / destination.name
        with ZipFile(staged, "w") as archive:
            for name, data in sorted(files.items()):
                entry = ZipInfo(f"{SLUG}/{name}", (2026, 11, 21, 0, 0, 0))
                entry.compress_type = ZIP_DEFLATED
                archive.writestr(entry, data)
        with ZipFile(staged) as archive:
            if any(archive.read(f"{SLUG}/{name}") != data for name, data in files.items()):
                raise ValueError("Skill archive verification failed.")
        if destination.exists():
            if destination.read_bytes() != staged.read_bytes():
                raise FileExistsError(f"A different skill archive exists at {destination}.")
        else:
            staged.rename(destination)


def install_personal() -> Path:
    folder = Path.home() / ".codex/skills"
    destination = folder / SLUG
    files = contents()
    if destination.exists():
        installed = {path.relative_to(destination).as_posix(): path.read_bytes()
                     for path in destination.rglob("*") if path.is_file()}
        if installed != files:
            raise FileExistsError(f"An existing local skill differs at {destination}.")
        return destination
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as temporary:
        staged = Path(temporary) / SLUG
        for name, data in files.items():
            path = staged / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        staged.rename(destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--install-personal", action="store_true", help="Install the skill in the local Codex profile.")
    mode.add_argument("--verify", action="store_true", help="Check the approved plate digests without writing a package.")
    options = parser.parse_args()
    if options.verify:
        print(f"Verified {len(contents()) - len(TEXT_FILES)} approved Chrysm plates.")
    else:
        package(OUTPUT)
        print(OUTPUT)
        if options.install_personal:
            print(install_personal())
