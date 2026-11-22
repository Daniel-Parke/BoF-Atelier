"""Inspect and import user-selected PS1 firmware locally, without executing it."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import zipfile

try:
    from .local_store import StoreError, canonical_bytes, member_path, plain_path
except ImportError:
    from local_store import StoreError, canonical_bytes, member_path, plain_path


ROM_BYTES = 512 * 1024
CATALOGUE = Path(__file__).resolve().parents[1] / "research/firmware-fingerprints.json"


def _is_zip(source: Path) -> bool:
    source = plain_path(source)
    if not source.is_file() or source.stat().st_size > 16 * 1024**2:
        raise StoreError("Select a local 512 KiB PlayStation BIOS or a ZIP under 16 MiB.")
    with source.open("rb") as stream:
        magic = stream.read(4)
    return magic in (b"PK\x03\x04", b"PK\x05\x06")


def _members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > 32 or sum(i.file_size for i in infos) > 16 * 1024**2:
        raise StoreError("Firmware ZIP exceeds the extraction limits.")
    found = []
    seen = set()
    for info in infos:
        name = member_path(info.filename.rstrip("/"))
        kind = stat.S_IFMT(info.external_attr >> 16)
        if (name.casefold() in seen or kind not in (0, stat.S_IFREG, stat.S_IFDIR)
                or info.flag_bits & 1 or info.external_attr & 0x400):
            raise StoreError("Firmware ZIP contains an ambiguous, linked or encrypted entry.")
        seen.add(name.casefold())
        if not info.is_dir() and info.file_size == ROM_BYTES:
            found.append(info)
    return found


def _read(source: Path, member: str | None) -> bytes:
    if not _is_zip(source):
        if member is not None or source.stat().st_size != ROM_BYTES:
            raise StoreError("This firmware format or size is unsupported. Select a 512 KiB raw image or ZIP.")
        with source.open("rb") as stream:
            data = stream.read(ROM_BYTES + 1)
    else:
        with zipfile.ZipFile(source) as archive:
            found = _members(archive)
            if member is not None:
                found = [i for i in found if i.filename == member]
            if len(found) != 1:
                choices = ", ".join(i.filename for i in found)
                raise StoreError(f"Select one 512 KiB firmware member. Candidates: {choices or 'none'}")
            with archive.open(found[0]) as stream:
                data = stream.read(ROM_BYTES + 1)
    if len(data) != ROM_BYTES:
        raise StoreError("The selected firmware length changed during reading.")
    return data


def _identify(data: bytes) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
    row = json.loads(CATALOGUE.read_text(encoding="utf-8"))["images"].get(md5)
    if row:
        evidence = "upstream-retail-fingerprint"
    elif data.startswith(b"OpenBIOS", 0x78):
        row = {"name": "OpenBIOS", "region": "Auto"}
        evidence = "openbios-marker-only"
    else:
        raise StoreError(f"Unrecognised 512 KiB firmware (SHA-256 {sha}). Check the dump or select another file.")
    return {**row, "id": sha, "sha256": sha, "md5": md5, "bytes": len(data),
            "evidence": evidence, "gameplay_validated": False}


def inspect_firmware(source: Path, member: str | None = None) -> dict:
    return _identify(_read(source, member))


def firmware_choices(source: Path) -> list[dict]:
    """Return identifiable members of this selected file, preserving exact ZIP filenames."""
    if not _is_zip(source):
        return [{**inspect_firmware(source), "member": None}]
    choices = []
    with zipfile.ZipFile(source) as archive:
        for info in _members(archive):
            with archive.open(info) as stream:
                data = stream.read(ROM_BYTES + 1)
            if len(data) != ROM_BYTES:
                raise StoreError("The advertised firmware length differs from the member data.")
            try:
                identity = _identify(data)
            except StoreError:
                continue
            choices.append({**identity, "member": info.filename})
    if not choices:
        raise StoreError("No recognised 512 KiB PlayStation firmware was found in this ZIP.")
    return choices


def discover_firmware(folder: Path) -> list[dict]:
    folder = plain_path(folder)
    results = []
    for count, candidate in enumerate(folder.iterdir(), start=1):
        if count > 4096:
            raise StoreError("Choose a smaller firmware directory.")
        if candidate.suffix.lower() not in {".bin", ".rom", ".bios", ".zip"}:
            continue
        try:
            results.extend({**row, "path": str(candidate)} for row in firmware_choices(candidate))
        except (OSError, ValueError, zipfile.BadZipFile, NotImplementedError):
            continue
    return sorted(results, key=lambda row: row["path"])


def import_firmware(source: Path, private_root: Path, *, member: str | None = None) -> dict:
    data = _read(source, member)
    info = _identify(data)
    store = plain_path(Path(private_root) / "firmware")
    store.mkdir(parents=True, exist_ok=True)
    final = plain_path(store / info["id"])
    receipt = {**info, "schema_version": 1, "origin": "user-selected-local-file"}
    with tempfile.TemporaryDirectory(dir=store, prefix=".import-") as temp:
        staged = Path(temp) / "firmware"
        staged.mkdir()
        (staged / "firmware.bin").write_bytes(data)
        (staged / "receipt.json").write_bytes(canonical_bytes(receipt))
        try:
            staged.rename(final)
        except OSError:
            if not final.is_dir():
                raise
            plain_path(final / "firmware.bin")
            plain_path(final / "receipt.json")
            if ((final / "firmware.bin").stat().st_size != len(data)
                    or (final / "firmware.bin").read_bytes() != data
                    or (final / "receipt.json").read_bytes() != canonical_bytes(receipt)):
                raise StoreError("The existing firmware store requires repair.")
    return {**receipt, "path": str(final / "firmware.bin")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "import", "discover"))
    parser.add_argument("source", type=Path)
    parser.add_argument("--private-root", type=Path, default=Path("private"))
    parser.add_argument("--member")
    args = parser.parse_args()
    try:
        if args.action == "discover":
            result = discover_firmware(args.source)
        elif args.action == "inspect":
            result = inspect_firmware(args.source, args.member)
        else:
            result = import_firmware(args.source, args.private_root, member=args.member)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, zipfile.BadZipFile, NotImplementedError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
