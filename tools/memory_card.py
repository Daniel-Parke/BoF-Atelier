"""Read a standard 128 KiB PlayStation memory card without changing it."""
from __future__ import annotations

import argparse
from functools import reduce
import hashlib
import json
import operator
from pathlib import Path
import re

try:
    from .local_store import StoreError, plain_path
except ImportError:
    from local_store import StoreError, plain_path


CARD_SIZE = 128 * 1024
BLOCK = 8192
FRAME = 128
GAME_FILENAMES = {"bof3": re.compile(rb"BASLUS-00422BOF3[0-9]{2}"),
                  "bof4": re.compile(rb"BASLUS-01324BOF4(?:0[0-9]|1[0-4])US")}
REFERENCE = "https://psx-spx.consoledev.net/controllersandmemorycards/#memory-card-data-format"


def inspect_card(data: bytes) -> dict:
    if len(data) != CARD_SIZE or data[:2] != b"MC":
        raise StoreError("Select a raw 128 KiB PlayStation memory card with an MC header.")
    warnings = []
    entries = [data[i * FRAME:(i + 1) * FRAME] for i in range(1, 16)]
    for number, frame in enumerate([data[:FRAME], *entries]):
        if reduce(operator.xor, frame) != 0:
            warnings.append(f"Frame {number} checksum differs.")
    saves = []
    used_blocks: set[int] = set()
    for number, entry in enumerate(entries, start=1):
        if entry[0] != 0x51:
            continue
        filename = entry[10:30].split(b"\0", 1)[0]
        game = next((g for g, pattern in GAME_FILENAMES.items() if pattern.fullmatch(filename)), None)
        length = int.from_bytes(entry[4:8], "little")
        chain = []
        block = number
        while True:
            if not 1 <= block <= 15 or block in chain or block in used_blocks:
                warnings.append(f"Block {number} has an invalid or shared chain.")
                break
            record = entries[block - 1]
            following = int.from_bytes(record[8:10], "little")
            expected = 0x51 if not chain else (0x53 if following == 0xffff else 0x52)
            if record[0] != expected:
                warnings.append(f"Block {block} has an unexpected allocation flag.")
                break
            chain.append(block)
            used_blocks.add(block)
            if following == 0xffff:
                break
            block = following + 1
        if not 0 < length <= len(chain) * BLOCK or length <= (len(chain) - 1) * BLOCK:
            warnings.append(f"Block count and file length differ at block {number}.")
        header = data[number * BLOCK:number * BLOCK + FRAME]
        has_header = header[:2] == b"SC"
        title = header[4:68].split(b"\0", 1)[0].decode("shift_jis", errors="replace") if has_header else None
        saves.append({"filename": filename.decode("ascii", errors="replace"), "game": game,
                      "title": title, "bytes": length, "blocks": chain, "has_save_header": has_header})
    for number, entry in enumerate(entries, start=1):
        if entry[0] in (0x52, 0x53) and number not in used_blocks:
            warnings.append(f"Allocated block {number} is outside a known file chain.")
    return {"sha256": hashlib.sha256(data).hexdigest(), "format": "raw-128KiB", "slots": saves,
            "free_blocks": sum(entry[0] == 0xa0 for entry in entries), "warnings": warnings,
            "gameplay_validated": False}


def inspect_file(source: Path) -> dict:
    source = plain_path(source)
    with source.open("rb") as stream:
        return inspect_card(stream.read(CARD_SIZE + 1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("card", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(inspect_file(args.card), indent=2, ensure_ascii=True))
    except (OSError, ValueError) as error:
        parser.exit(2, f"{error}\n")
