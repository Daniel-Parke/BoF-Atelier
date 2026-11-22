"""Recognise a saved area on the two documented US discs. Never open a card for writing."""
from __future__ import annotations

from functools import reduce
import operator
from pathlib import Path
import stat

from . import memory_card
from .local_store import plain_path
from .managed_cards import SERIALS


# Exact import receipts. Area IDs and checksum evidence are in verification/GUIDE-STORY-CONTEXT.md.
REVISIONS = {
    "bof3": "1d97aa04983896b88ef1cf1cb55f7e1373a03e6fc893d7a1860e2c3d4c8e083e",
    "bof4": "718d17036fbd837d46c95eb4b880162e789cf5d9dfd1bbc297edadd7fe1865bb",
}

# Many maps recur. Qualify the pair of scenario and saved map; leave generic camps
# and world maps unassigned. The reading page describes this place within that visit.
III_SAVED_AREAS = {
    0: {24: "mine"},
    1: {7: "cedar", 8: "cedar", 9: "cedar", 10: "cedar", 14: "cedar", 19: "cedar",
        22: "glaus", 23: "glaus"},
    2: {26: "mcneil-manor", 27: "mcneil-manor", 28: "mcneil-manor"},
    3: {41: "wyndia", 51: "wyndia", 56: "wyndia"},
    4: {40: "momo-tower", 42: "momo-tower", 44: "momo-tower", 48: "momo-tower"},
    5: {49: "dump", 52: "dump", 50: "contest"},
    6: {57: "rhapala", 94: "rhapala", 77: "lighthouse"},
    7: {82: "angel-tower", 83: "angel-tower", 84: "angel-tower", 85: "angel-tower"},
    8: {108: "mine-return", 21: "syn-city", 35: "syn-city"},
    9: {49: "plant", 52: "plant"},
    10: {105: "guardians", 120: "guardians"},
    12: {133: "black-ship", 135: "black-ship", 137: "black-ship", 188: "black-ship"},
    13: {143: "dragnier", 144: "dragnier", 145: "colony"},
    14: {138: "factory", 139: "factory", 140: "factory", 189: "desert",
         146: "caer-xhan", 147: "caer-xhan", 148: "caer-xhan", 150: "caer-xhan",
         167: "myria-lab", 168: "myria-lab", 170: "myria-lab", 172: "eden"},
    15: {172: "eden", 198: "eden"},
}

# Two independently played US files resume at this diary. Other rooms in Myria
# Station and the post-clear return to Dragnier have different position records.
III_FINAL_DIARY_POSITION = bytes.fromhex("a6 00 00 07 00 00 40 00")

# Retail AREAE005's named node table. Keys are the active scenario and the
# integer resume tile (not the return tile or Shift cursor). Values are the row
# index, the bit that unlocks the node in this scenario, and the walkthrough ID.
IV_WORLD_VISITS = {
    (2, 31, 75): (61, 8, "tomb"),
    (4, 69, 82): (4, 26, "chamba"),
    (3, 61, 85): (6, 15, "dam-kyria"),
    (3, 56, 83): (7, 16, "dam-kyria"),
    (5, 62, 72): (10, 0, "synesta"),
    (6, 101, 97): (30, 23, "golden-plains"),
    (9, 90, 71): (42, 5, "wyndia"),
    (9, 106, 96): (35, 8, "wyndia"),
    (10, 95, 65): (44, 1, "pung-tap"),
    (10, 87, 69): (91, 11, "chek"),
    (11, 80, 68): (96, 21, "sinchon"),
    (13, 34, 97): (50, 10, "sanctum"),
    (14, 72, 46): (84, 10, "shikk"),
    (14, 45, 14): (80, 30, "lyp"),
    (17, 14, 73): (69, 0, "chiqua"),
}
IV_NODE_TABLE = 0x800fae9c
IV_NODE_BYTES = 20
IV_DIARY_VISITS = {
    (6, 0x022d, 1): "ludia",
    (22, 0x04a8, 2): "meeting",
}


def _iv_world_visit(scenario: int, block: bytes) -> str | None:
    x = int.from_bytes(block[0xff8:0xffa], "little")
    z = int.from_bytes(block[0xffa:0xffc], "little")
    pointer = int.from_bytes(block[0xf5c:0xf60], "little")
    if (scenario, x, z) == (2, 76, 76) and pointer == IV_NODE_TABLE:
        return "north-desert" if block[0x100c:0x1010] == bytes(4) else None
    # The same ordinary world-map record can describe either arrival or return.
    # Named visits need a witness from the session that wrote this file.
    return None


def _saved_area(game: str, block: bytes) -> str | None:
    if block[:2] != b"SC" or block[2] not in (0x11, 0x12, 0x13) or block[3] != 1:
        return None
    if game == "bof3":
        # The PSX slot has a 0x200-byte header before its 0x10b0-byte game block.
        expected = int.from_bytes(block[0x270:0x272], "little")
        actual = (sum(block[0x200:0x270]) + sum(block[0x272:0x12b0])) & 0xffff
        if actual != expected or block[0x202] != 2:
            return None
        if block[0x200] == 15 and block[0x224:0x22c] == III_FINAL_DIARY_POSITION:
            return "eden"
        area = int.from_bytes(block[0x224:0x226], "little")
        return III_SAVED_AREAS.get(block[0x200], {}).get(area)

    if reduce(operator.xor, block[:0x184f]) != block[0x184f]:
        return None
    scenario, section = block[0xff4:0xff6]
    area = int.from_bytes(block[0xff6:0xff8], "little")
    if area == 0x0805 and section == 0:
        return _iv_world_visit(scenario, block)
    if scenario == 2 and area == 0x0414 and section in (2, 3):
        return "north-desert"
    if scenario == 4 and area in (0x1000, 0x0201, 0x0204):
        return "sarai"
    return IV_DIARY_VISITS.get((scenario, area, section))


def _card_stamp(path: Path) -> tuple[int, int, int, int]:
    info = plain_path(path).stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size != memory_card.CARD_SIZE:
        raise ValueError("Unsupported memory card")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def saved_story(game: str, record: dict | None, paths: dict[int, Path]) -> dict[str, str | int]:
    """All occupied files on these ports must independently identify the same saved area."""
    if (game not in REVISIONS or not record or not record.get("verified")
            or record.get("game") != game or record.get("serial") != SERIALS[game]
            or record.get("fingerprint") != REVISIONS[game] or not paths or not paths.keys() <= {1, 2}):
        return {}
    try:
        stamps = {port: _card_stamp(path) for port, path in paths.items()}
        if len({stamp[:2] for stamp in stamps.values()}) != len(stamps):
            return {}
        places = set()
        for path in paths.values():
            with plain_path(path).open("rb") as reader:
                data = reader.read(memory_card.CARD_SIZE + 1)
            card = memory_card.inspect_card(data)
            if card["warnings"] or any(data[i * memory_card.FRAME] not in {0x51, 0xa0, 0xa1, 0xa2, 0xa3}
                                       for i in range(1, 16)):
                return {}
            filenames = set()
            for slot in card["slots"]:
                if (slot["filename"] in filenames or slot["game"] != game or not slot["has_save_header"]
                        or slot["bytes"] != memory_card.BLOCK or len(slot["blocks"]) != 1):
                    return {}
                filenames.add(slot["filename"])
                start = slot["blocks"][0] * memory_card.BLOCK
                block = data[start:start + memory_card.BLOCK]
                place = _saved_area(game, block)
                if not place:
                    return {}
                # McNeil and Cedar Woods share a chapter. Name the village only when all files agree.
                village = game == "bof3" and place == "cedar" and int.from_bytes(block[0x224:0x226], "little") == 7
                places.add((place, village))
                if len(places) > 1:
                    return {}
        if places and all(_card_stamp(path) == stamps[port] for port, path in paths.items()):
            place, village = places.pop()
            result = {"game": game, "place": place, "source": "Last in-game save"}
            return dict(result, floorId=7) if village else result
    except (OSError, ValueError):
        pass
    return {}
