"""Build private, top-down Field Guide images from a verified original disc."""
from __future__ import annotations

import base64
import re
import struct
import zlib
from collections import deque

from .import_games import file_id
from .inspect_disc import RawDiscReader


def iv_floor_block(reader, entry):
    header = reader.read_logical(entry["lba"], 2048)
    count, version = struct.unpack_from("<II", header)
    if version != 1 or header[8:16] != b"MATH_TBL" or count > 127:
        raise ValueError("Unknown IV field container.")
    offset = 2048
    for i in range(count):
        length, address = struct.unpack_from("<II", header, 16 + i*16)
        if offset + length > entry["bytes"]:
            raise ValueError("IV field section exceeds its file.")
        if address == 0x80069800:
            if not 200 <= length <= 2**20:
                raise ValueError("Unsupported IV floor section size.")
            return reader.read_logical(entry["lba"] + offset//2048, length)
        offset += (length+2047)//2048*2048
    raise ValueError("No floor data in this scene.")


def iv_tile_class(value):
    if value in (0x10, 0x11, 0x12, 0x13, 0x30, 0x50, 0xa3, 0xff, 0xf0, 0xf1, 0xf2) or value >> 4 == 4:
        return 0
    return {7: 2, 12: 2, 10: 3, 14: 4, 11: 4}.get(value >> 4, 1)


IV_PALETTE = bytes(iv_tile_class(i) for i in range(256))


def iv_floor_grid(block, section, landmarks=(), *, enclosed=False):
    def pointer(offset):
        value, = struct.unpack_from("<I", block, offset)
        if value <= 0 or value >= len(block):
            raise ValueError("Invalid IV floor pointer.")
        return value

    if len(block) < 200 or not 0 <= section < min(32, block[3]):
        raise ValueError("This IV floor is unavailable.")
    desc = pointer(0xc4 + 4*section)
    terrain, attributes = struct.unpack_from("BB", block, desc)
    if terrain >= 40 or attributes >= 8:
        raise ValueError("Invalid IV floor indices.")
    width, height = struct.unpack_from("<HH", block, pointer(4+4*terrain))
    width *= 2
    height *= 2
    start = pointer(0xa4+4*attributes)
    if not (0 < width <= 256 and 0 < height <= 256 and start+width*height <= len(block)):
        raise ValueError("Invalid IV floor dimensions.")
    attributes = block[start:start+width*height]
    grid = attributes.translate(IV_PALETTE)
    anchors = {(p["x"], p["z"]) for p in landmarks}
    anchors.update((i % width, i // width) for i, colour in enumerate(grid) if colour == 3)
    rows = [bytearray(grid[i:i+width]) for i in range(0, len(grid), width)]
    # Zero is also the ordinary walking attribute. Blank margins therefore look
    # like floors until separated from the entered room by its collision walls.
    if anchors:
        # Some stacked platforms meet the empty margin at a door tile. On those
        # surveyed decks the door seals the margin. Open rooms can instead
        # extend to the edge, so a doorway must keep its connected floor.
        def margin_candidate(x, y):
            return attributes[y*width+x] == 0 if enclosed else rows[y][x] != 0

        edges = [(x,y) for x in range(width) for y in (0,height-1)]
        edges.extend((x,y) for y in range(height) for x in (0,width-1))
        visited = set()
        for edge in edges:
            if edge in visited or not margin_candidate(*edge):
                continue
            queue = deque([edge])
            region = {edge}
            while queue:
                x, y = queue.popleft()
                for nx, ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if (0 <= nx < width and 0 <= ny < height and
                            margin_candidate(nx, ny) and (nx,ny) not in region):
                        region.add((nx,ny))
                        queue.append((nx,ny))
            visited.update(region)
            if region.isdisjoint(anchors) and any(0 <= x < width and 0 <= y < height and rows[y][x] for x,y in anchors):
                for x, y in region:
                    rows[y][x] = 0
    return [bytes(row) for row in rows]


def floor_image(rows):
    """Crop unused margins but retain the origin for original tile coordinates."""
    if not rows or not 1 <= len(rows) <= 256 or not 1 <= len(rows[0]) <= 256:
        raise ValueError("Unsupported floor dimensions.")
    if any(len(row) != len(rows[0]) or max(row) > 4 for row in rows):
        raise ValueError("Inconsistent floor grid.")
    valid = [(x, y) for y, row in enumerate(rows) for x, tile in enumerate(row) if tile]
    if not valid:
        raise ValueError("This floor is empty.")
    xs, ys = zip(*valid)
    left, right = max(0, min(xs)-1), min(len(rows[0]), max(xs)+2)
    top, bottom = max(0, min(ys)-1), min(len(rows), max(ys)+2)
    w, h = right-left, bottom-top

    def chunk(kind, data):
        return struct.pack(">I", len(data))+kind+data+struct.pack(">I", zlib.crc32(kind+data))

    palette = bytes.fromhex("20332f dfcfaa 85bbad ec997a a5aa82 a18f70 eee4c5 2d4039 d3c4a3")
    # Three samples per tile leave room for a narrow edge along collision walls.
    # The original grid coordinates still determine the positions of every pin.
    pixels = bytearray()
    for y in range(top,bottom):
        bands = [bytearray(b"\0") for _ in range(3)]
        for x in range(left,right):
            tile = rows[y][x]
            if tile == 0:
                for k, band in enumerate(bands):
                    band.extend((7,0,0) if x%4 == y%4 == k == 0 else (0,0,0))
                continue
            west = x == 0 or not rows[y][x-1]
            east = x+1 == len(rows[y]) or not rows[y][x+1]
            north = y == 0 or not rows[y-1][x]
            south = y+1 == len(rows) or not rows[y+1][x]
            for k, band in enumerate(bands):
                if tile == 1:
                    ink = 6 if north and k == 0 else 5 if south and k == 2 else 1
                    band.extend((6 if west else ink, ink, 5 if east else ink))
                else:
                    band.extend((tile,tile,tile))
        pixels.extend(b"".join(bands))
    png = (b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack(">IIBBBBB", w*3,h*3,8,3,0,0,0))
           + chunk(b"PLTE", palette)+chunk(b"IDAT", zlib.compress(pixels))+chunk(b"IEND", b""))
    return {"url": "data:image/png;base64,"+base64.b64encode(png).decode("ascii"),
            "left": left, "top": top, "width": w, "height": h}


def read_floors(verified_disc, route):
    _, track, identity, disc, game = verified_disc
    if game not in {"bof3", "bof4"}:
        return {}
    by_id = {}
    pattern = r"/AREA(\d{3})\.EMI;1$" if game == "bof3" else r"/WORLD/AREA([SDEM])(\d{3})\.EMI;1$"
    for entry in disc["file_table"]:
        match = re.search(pattern, entry["path"])
        if match:
            mid = int(match[1]) if game == "bof3" else {"S":512,"D":1024,"E":2048,"M":4096}[match[1]] + int(match[2])
            if mid in by_id:
                raise ValueError("Ambiguous disc floor identity.")
            by_id[mid] = entry
    sheets = {}
    requested = {}
    enclosed = set()
    for stop in route:
        for floor in stop.get("floors", []):
            if "mapId" in floor:
                key = (floor["mapId"], floor["section"])
                requested.setdefault(key, []).extend(floor.get("landmarks", []))
                if floor.get("enclosedDeck"):
                    enclosed.add(key)
    last_id, block = None, None
    for mid, section in sorted(requested):
        entry = by_id.get(mid)
        if not entry:
            continue
        reader = RawDiscReader(track)
        try:
            if game == "bof4":
                if last_id != mid:
                    block = iv_floor_block(reader, entry)
                    last_id = mid
                rows = iv_floor_grid(block, section, requested[mid, section], enclosed=(mid, section) in enclosed)
            else:
                from .iii_floors import floor_grid
                rows = floor_grid(reader, entry, section)
            sheets[f"{mid}.{section}"] = floor_image(rows)
        except (ValueError, IndexError, struct.error):
            continue
    if identity != file_id(track):
        raise ValueError("The imported track changed while reading the floors.")
    return sheets
