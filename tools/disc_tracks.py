"""Read logical track ranges of the supplied US IV image without producing split images."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import BinaryIO

from .inspect_disc import RawDiscReader, inspect_disc, RAW_SECTOR_BYTES
from .local_store import StoreError, atomic_bytes, canonical_bytes, member_path, plain_path


RANGES = ((0, 274263, "24be71b32aeb52a930bc08dccda5db61e904de8a"),
          (274263, 292651, "dc0fa59967976a4e37315a6b63a7bbbc9536a85a"))
EXECUTABLE_SHA1 = "4a658dca8775b569ae876ceecf5742b46eecff58"


class TrackView:
    """Read sector-aligned ranges through a caller-owned read-only disc handle."""
    def __init__(self, file: BinaryIO, first: int, end: int):
        if type(first) is not int or type(end) is not int or not 0 <= first < end:
            raise StoreError("Invalid physical track boundaries.")
        self.file, self.first, self.count = file, first, end - first

    def read(self, sector: int, count: int = 1) -> bytes:
        if (type(sector) is not int or type(count) is not int or count > 1024
                or not 0 <= sector <= self.count or not 0 <= count <= self.count - sector):
            raise StoreError("Requested sectors exceed the track view or the per-read budget.")
        self.file.seek((self.first + sector) * RAW_SECTOR_BYTES)
        data = self.file.read(count * RAW_SECTOR_BYTES)
        if len(data) != count * RAW_SECTOR_BYTES:
            raise StoreError("Short disc read. The image may have changed.")
        return data

    def sha1(self) -> str:
        digest = hashlib.sha1()
        for start in range(0, self.count, 1024):
            digest.update(self.read(start, min(1024, self.count - start)))
        return digest.hexdigest()


def inspect_iv(private: Path) -> dict:
    directory = plain_path(private / "games/bof4")
    receipt = json.loads(plain_path(directory / "import-receipt.json").read_bytes())
    if receipt["serial"] != "SLUS-01324" or not receipt["reference_match"]:
        raise StoreError("This investigation requires the reference-matched US IV disc.")
    bins = [entry for entry in receipt["entries"] if entry["path"].lower().endswith(".bin")]
    if len(bins) != 1:
        raise StoreError("Expected the supplied single-BIN layout.")
    source = plain_path(directory / member_path(bins[0]["path"]))
    if source.stat().st_size != RANGES[-1][1] * RAW_SECTOR_BYTES:
        raise StoreError("The image size differs from the reference table of contents.")
    tracks = []
    with source.open("rb") as stream:
        for first, end, reference in RANGES:
            view = TrackView(stream, first, end)
            digest = view.sha1()
            if digest != reference:
                raise StoreError("Logical track bytes differ from the independent reference.")
            tracks.append({"first_lba": first, "end_lba_exclusive": end, "sectors": view.count, "sha1": digest})
    iso = inspect_disc(source)
    exe = next(entry for entry in iso["file_table"] if entry["path"] == iso["boot_executable"])
    if exe["lba"] + (exe["bytes"] + 2047) // 2048 > RANGES[0][1]:
        raise StoreError("The boot executable does not fit inside track 1.")
    digest = hashlib.sha1(RawDiscReader(source).read_logical(exe["lba"], exe["bytes"])).hexdigest()
    if digest != EXECUTABLE_SHA1:
        raise StoreError("The boot executable differs from the native importer's required revision.")
    result = {"game": "bof4", "game_fingerprint": receipt["content_fingerprint"], "tracks": tracks,
              "native_importer_commit": "c6ad1cf27a2638870a20571da13db68bc5f7193d", "exe_sha1": digest,
              "range_basis": "Redump reference track 2 INDEX 00", "native_gameplay": "unqualified"}
    atomic_bytes(private / "lab/native/bof4/logical-track-receipt.json", canonical_bytes(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, default=Path("private"))
    print(json.dumps(inspect_iv(parser.parse_args().private), indent=2))
