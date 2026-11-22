"""Read a static US BoF III field floor from the caller's verified disc.

The map header's first two bytes are in cells. Its word at 0x14 points,
in four-byte units, to the row-major cell attributes. The high nibble
classification follows AreaMap_CellBlocked (PSX routine 0x801A3100).
Scripted changes, height differences, actors and locks can affect movement.
"""
from __future__ import annotations

import struct

from .inspect_disc import RawDiscReader


FLOOR_ADDRESS = 0x80104000
SOLID_NIBBLES = frozenset((1, 2, 3, 4, 5, 10, 11, 15))
CELL_CLASS = bytes(int(value >> 4 not in SOLID_NIBBLES) for value in range(256))


def floor_grid(reader: RawDiscReader, entry: dict, section: int) -> list[bytes]:
    if type(section) is not int or section != 0:
        raise ValueError("This III field has one static ground plan.")
    size, lba = entry["bytes"], entry["lba"]
    if type(lba) is not int or lba < 0 or type(size) is not int or not 2048 <= size <= 16 * 1024 * 1024:
        raise ValueError("Invalid III field container extent.")
    header = reader.read_logical(lba, 2048)
    if len(header) != 2048 or header[8:16] != b"MATH_TBL":
        raise ValueError("Invalid III field container.")
    count, version = struct.unpack_from("<II", header)
    if version != 1 or not 1 <= count <= 127:
        raise ValueError("Unknown III field container header.")
    offset = 2048
    floor = None
    for index in range(count):
        length, address, _, kind = struct.unpack_from("<IIIH", header, 16 + 16 * index)
        if length > size - offset:
            raise ValueError("III field payload exceeds its container.")
        if address == FLOOR_ADDRESS and kind == 0:
            if floor is not None or not 44 <= length <= 2 * 1024 * 1024:
                raise ValueError("Missing or ambiguous III field plane.")
            floor = (lba + offset // 2048, length)
        offset += (length + 2047) // 2048 * 2048
    if floor is None:
        raise ValueError("No static III floor in this field.")
    start, length = floor
    data = reader.read_logical(start, length)
    if len(data) != length:
        raise ValueError("Incomplete III floor payload.")
    width, height = data[:2]
    cell_count = width * height
    attributes = 4 * struct.unpack_from("<H", data, 0x14)[0]
    if not width or not height or attributes < 44 + cell_count * 4 or attributes + cell_count > length:
        raise ValueError("III floor dimensions exceed the field payload.")
    tiles = data[attributes:attributes + cell_count].translate(CELL_CLASS)
    return [tiles[at:at + width] for at in range(0, cell_count, width)]
