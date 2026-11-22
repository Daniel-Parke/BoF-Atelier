"""Synthetic ordinary cards only. No window, controller, emulator or game image is required."""
from functools import reduce
import json
import operator
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shell.guide_book import read_book
from shell.service import PlayerService
from tools import guide_story, memory_card, managed_cards
from test_shell_service import Pad


def record(game):
    return {"id": game, "game": game, "serial": managed_cards.SERIALS[game], "verified": True,
            "reference": True, "tracks": 2, "cue": "synthetic.cue", "fingerprint": guide_story.REVISIONS[game]}


def slot(game, scenario, area, *, section=0, node=0, progress=0, tile=(76, 76),
         position_tail=bytes(6), variant=0):
    block = bytearray(memory_card.BLOCK)
    block[:4] = b"SC\x11\x01"
    block[4:11] = b"Fixture"
    block[0x400] = variant  # same place, different saved character data
    if game == "bof3":
        block[0x200:0x202] = scenario.to_bytes(2, "little")
        block[0x202] = 2
        block[0x224:0x226] = area.to_bytes(2, "little")
        block[0x226:0x22c] = position_tail
        block[0x270:0x272] = (sum(block[0x200:0x12b0]) & 0xffff).to_bytes(2, "little")
    else:
        block[0xff4:0xff8] = bytes((scenario, section)) + area.to_bytes(2, "little")
        block[0xf5c:0xf60] = node.to_bytes(4, "little")
        block[0xff8:0xffc] = tile[0].to_bytes(2, "little") + tile[1].to_bytes(2, "little")
        offset = 0x1004 + 4 * scenario
        block[offset:offset + 4] = progress.to_bytes(4, "little")
        block[0x184f] = reduce(operator.xor, block[:0x184f])
    return block


def card(*entries):
    data = bytearray(memory_card.CARD_SIZE)
    data[:2] = b"MC"
    for index in range(1, 16):
        entry = index * 128
        data[entry] = 0xa0
        data[entry + 8:entry + 10] = b"\xff\xff"
    for index, filename, block in entries:
        entry = index * 128
        data[entry] = 0x51
        data[entry + 4:entry + 8] = memory_card.BLOCK.to_bytes(4, "little")
        data[entry + 10:entry + 10 + len(filename)] = filename.encode("ascii")
        data[index * memory_card.BLOCK:(index + 1) * memory_card.BLOCK] = block
    for index in range(16):
        entry = index * 128
        data[entry + 127] = reduce(operator.xor, data[entry:entry + 127])
    return bytes(data)


III = "BASLUS-00422BOF300"
IV = "BASLUS-01324BOF400US"


class GuideStoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.card = self.root / "card.mcd"

    def read(self, game, data):
        self.card.write_bytes(data)
        result = guide_story.saved_story(game, record(game), {2: self.card})
        self.assertEqual(self.card.read_bytes(), data)
        return result

    def test_different_slots_stats_and_block_positions_resolve_without_a_fingerprint(self):
        for index, variant in ((1, 0), (7, 1), (15, 255)):
            with self.subTest(index=index):
                body = card((index, III[:-2] + "02", slot("bof3", 1, 10, variant=variant)))
                self.assertEqual(self.read("bof3", body), {"game": "bof3", "place": "cedar", "source": "Last in-game save"})

    def test_iii_revisits_chapters_and_generic_camps(self):
        for chapter, area, expected in ((0, 24, "mine"), (1, 23, "glaus"), (5, 49, "dump"), (9, 49, "plant"),
                                        (14, 189, "desert"), (14, 170, "myria-lab"), (15, 198, "eden"),
                                        (2, 10, None), (1, 90, None), (1, 0x010a, None), (16, 24, None)):
            with self.subTest(chapter=chapter, area=area):
                self.assertEqual(self.read("bof3", card((1, III, slot("bof3", chapter, area)))).get("place"), expected)

    def test_mcneil_inn_selects_village_only_when_all_saves_agree(self):
        inn = (1, III, slot("bof3", 1, 7))
        self.assertEqual(self.read("bof3", card(inn)).get("floorId"), 7)
        woodland = (2, III[:-2] + "02", slot("bof3", 1, 10))
        self.assertEqual(self.read("bof3", card(inn, woodland)), {})

    def test_final_iii_diary_requires_the_observed_visit_and_room(self):
        room = bytes.fromhex("00 07 00 00 40 00")
        for word, area, tail, expected in (
                (0x400f, 166, room, "eden"), (0x000f, 166, room, "eden"),
                (0x400e, 166, room, None), (0x400f, 166, bytes(6), None),
                (0x400f, 165, room, None), (0x000f, 143, room, None)):
            with self.subTest(word=word, area=area, tail=tail):
                body = slot("bof3", word, area, position_tail=tail, variant=66)
                self.assertEqual(self.read("bof3", card((9, III, body))).get("place"), expected)

    def test_every_supported_match_opens_a_bundled_route_page(self):
        books = Path(__file__).resolve().parents[1] / "design/field-guide/wiki"
        for game in ("bof3", "bof4"):
            route_ids = {place["id"] for place in read_book(books, game)["route"]}
            if game == "bof3":
                locations = [slot(game, chapter, area) for chapter, areas in guide_story.III_SAVED_AREAS.items()
                             for area in areas]
                locations.append(slot(game, 0x400f, 166, position_tail=bytes.fromhex("00 07 00 00 40 00")))
            else:
                locations = [slot(game, 2, 0x0805, node=0x800fae9c), slot(game, 2, 0x0414, section=3),
                             slot(game, 4, 0x1000), slot(game, 4, 0x0201), slot(game, 4, 0x0204),
                             *(slot(game, stage, area, section=section) for stage, area, section
                               in guide_story.IV_DIARY_VISITS)]
                for _, _, page in guide_story.IV_WORLD_VISITS.values():
                    self.assertIn(page, route_ids)
            for location in locations:
                self.assertIn(guide_story._saved_area(game, location), route_ids)

    def test_iv_region_node_section_and_scenario(self):
        for scenario, area, section, node, progress, expected in (
                (2, 0x0805, 0, 0x800fae9c, 0, "north-desert"),
                (2, 0x0805, 0, 0x800faeb0, 0, None),  # next node shares the same world map
                (2, 0x0805, 0, 0x800fae9c, 2, None),
                (4, 0x0805, 0, 0x800fae9c, 0, None),
                (2, 0x0414, 2, 0, 0, "north-desert"), (2, 0x0414, 0, 0, 0, None),
                (4, 0x1000, 0, 0, 0, "sarai"), (4, 0x0201, 2, 0, 0, "sarai"),
                (6, 0x1000, 0, 0, 0, None), (6, 0x022d, 1, 0, 0, "ludia"),
                (6, 0x022d, 0, 0, 0, None), (4, 0x022d, 1, 0, 0, None)):
            with self.subTest(scenario=scenario, area=area, section=section, node=node, progress=progress):
                block = slot("bof4", scenario, area, section=section, node=node, progress=progress, variant=12)
                self.assertEqual(self.read("bof4", card((5, IV, block))).get("place"), expected)

    def test_unwitnessed_world_saves_stay_manual_even_inside_the_unlock_window(self):
        # Independently transcribed US world-map records for Shikk, Chek and Chiqua.
        for scenario, tile, pointer, bit, expected in (
                (14, (72, 46), 0x800fb52c, 10, "shikk"),
                (10, (87, 69), 0x800fb5b8, 11, "chek"),
                (17, (14, 73), 0x800fb400, 0, "chiqua")):
            supported = dict(tile=tile, node=pointer, progress=(1 << bit) | ((1 << bit) - 1))
            for stage, args in (
                    (scenario, supported),
                    (scenario, supported | {"progress": 1 << bit}),
                    (scenario, supported | {"progress": (1 << bit) - 1}),
                    (scenario, supported | {"progress": (1 << bit) | (1 << (bit + 1))}),
                    (scenario, supported | {"tile": (tile[0] + 1, tile[1])}),
                    (scenario, supported | {"node": pointer + 20}),
                    (scenario, supported | {"section": 1}), (23, supported)):
                with self.subTest(stage=stage, args=args):
                    body = slot("bof4", stage, 0x0805, **args)
                    self.assertEqual(self.read("bof4", card((3, IV, body))), {})

    def test_iv_castle_diary_and_cleared_cards_do_not_share_a_walkthrough(self):
        for scenario, area, section, expected in (
                (22, 0x04a8, 2, "meeting"), (22, 0x04a8, 1, None), (22, 0x04a7, 2, None),
                (16, 0x04a8, 2, None), (23, 0x0805, 0, None), (27, 0x0805, 0, None)):
            with self.subTest(scenario=scenario, area=area, section=section):
                body = slot("bof4", scenario, area, section=section, node=0x800fb2c0, tile=(22, 95))
                self.assertEqual(self.read("bof4", card((1, IV, body))).get("place"), expected)
        stale = slot("bof4", 2, 0x0805, node=0x800fae9c, tile=(22, 95))
        self.assertEqual(self.read("bof4", card((5, IV, stale))), {})
        final = slot("bof4", 22, 0x04a8, section=2)
        earlier = slot("bof4", 6, 0x022d, section=1)
        self.assertEqual(self.read("bof4", card((1, IV, final), (2, "BASLUS-01324BOF411US", earlier))), {})

    def test_distinct_directory_payload_and_revision_checks(self):
        for game, name, area in (("bof3", III, 10), ("bof4", IV, 0x1000)):
            with self.subTest(game=game):
                block = slot(game, 1 if game == "bof3" else 4, area)
                original = card((1, name, block))
                self.card.write_bytes(original)
                for changed in ({"verified": False}, {"serial": "OTHER"}, {"fingerprint": "0" * 64}, {"game": "other"}):
                    self.assertEqual(guide_story.saved_story(game, record(game) | changed, {1: self.card}), {})
                block[0x400] ^= 1  # card directory still verifies, game body does not
                self.assertEqual(self.read(game, card((1, name, block))), {})
                self.assertEqual(self.read(game, original[:4096]), {})
                damaged_directory = bytearray(original)
                damaged_directory[254] ^= 1
                self.assertEqual(self.read(game, damaged_directory), {})

    def test_ambiguous_foreign_blank_missing_and_changing_cards(self):
        game = record("bof3")
        block = slot("bof3", 1, 10)
        self.assertEqual(self.read("bof3", card((2, III, block), (3, III, block))), {})
        self.assertEqual(self.read("bof3", card((2, III, block), (3, III[:-2] + "01", slot("bof3", 1, 23)))), {})
        self.assertEqual(self.read("bof3", card((2, III, block), (3, III[:-2] + "01", slot("bof3", 1, 90)))), {})
        self.assertEqual(self.read("bof3", card((2, III, block), (3, IV, slot("bof4", 4, 0x1000)))), {})
        self.assertEqual(self.read("bof3", card()), {})
        self.assertEqual(self.read("bof3", card((4, "BASLUS-00422BOF300X", block))), {})
        self.card.write_bytes(card((2, III, block)))
        self.assertEqual(guide_story.saved_story("bof3", game, {1: self.card, 2: self.card}), {})
        self.assertEqual(guide_story.saved_story("bof3", game, {1: self.card, 2: self.root / "missing"}), {})
        self.assertEqual(guide_story.saved_story("bof3", game, {3: self.card}), {})
        with patch.object(guide_story, "_card_stamp", side_effect=[(1, 2, 131072, 7), (1, 3, 131072, 7)]):
            self.assertEqual(guide_story.saved_story("bof3", game, {1: self.card}), {})

    def test_distinct_agreeing_slots_identify_a_page_without_choosing_a_slot(self):
        data = card((2, III, slot("bof3", 1, 10)), (9, III[:-2] + "01", slot("bof3", 1, 8, variant=4)))
        self.assertEqual(self.read("bof3", data)["place"], "cedar")
        second = self.root / "other.mcd"
        second.write_bytes(card((13, III, slot("bof3", 1, 9, variant=99))))
        self.assertEqual(guide_story.saved_story("bof3", record("bof3"), {1: self.card, 2: second})["place"], "cedar")
        second.write_bytes(card((13, III, slot("bof3", 1, 7, variant=99))))
        self.assertEqual(guide_story.saved_story("bof3", record("bof3"), {1: self.card, 2: second}), {})

    def test_open_rereads_only_the_running_branch_and_keeps_named_entry(self):
        service = PlayerService(self.root, Pad(), channel="lab")
        self.addCleanup(service.close)
        service.game = "bof3"
        service.records = [record(service.game)]
        branch = self.root / "lab" / "reference-play" / "bof3" / "branch"
        branch.mkdir(parents=True)
        active = branch / "disposable1.mcd"
        active.write_bytes(card((1, III, slot("bof3", 1, 10))))
        service.played_cards = {"game": "bof3", "channel": "lab", "backend": "reference",
                                "route": "restored/" + "a" * 32, "paths": {1: active}, "lock": service._edition()}
        service.process = object()  # model of an already open Guide, without a native window or input
        service.guide_session.reading = True
        service.action("openGuide", "genes")
        self.assertEqual(service.snapshot()["guideStory"]["place"], "cedar")
        self.assertEqual(service.snapshot()["guideEntry"], "genes")
        # Move the one save without changing its title; snapshot polls do no I/O.
        active.write_bytes(card((1, III, slot("bof3", 1, 23))))
        with patch.object(guide_story, "saved_story", side_effect=AssertionError("read on a poll")):
            self.assertEqual(service.snapshot()["guideStory"]["place"], "cedar")
        service.action("openGuide")
        self.assertEqual(service.snapshot()["guideStory"]["place"], "glaus")
        for operation in (
                {"route": "checkpoint/" + "b" * 32},
                {"game": "bof4"},
                {"lock": service._edition() | {"profile": "Personal"}},
                {"lock": service._edition() | {"content": "wrong"}},
                {"channel": "play"},
                {"paths": {}}):
            original = service.played_cards
            service.played_cards = original | operation
            service.action("openGuide")
            self.assertEqual(service.snapshot()["guideStory"], {}, operation)
            service.played_cards = original
        active.write_bytes(card())
        service.action("openGuide")
        self.assertEqual(service.snapshot()["guideStory"], {})

    def test_closed_reference_uses_only_the_selected_session_receipt(self):
        service = PlayerService(self.root, Pad(), channel="lab")
        self.addCleanup(service.close)
        service.game = "bof4"
        game_record = record("bof4") | {"cue": str(self.root / "fixture.cue")}
        Path(game_record["cue"]).write_text("Synthetic fixture", encoding="ascii")
        service.records = [game_record]
        service.runtime["can_launch"] = False
        selected = "20261121T100000000000Z"
        session = self.root / "lab/reference-play/bof4" / selected
        session.mkdir(parents=True)
        from tools import runtime_setup
        configuration = {"pid": 1234, "created": "earlier-process", "game": "bof4", "backend": "ref",
                         "version": "test", "restored_branch": None,
                         "cue_sha256": runtime_setup._digest(Path(game_record["cue"])),
                         "firmware_sha256": runtime_setup._catalogue()["openbios-psx-rom"]["member"]["sha256"]}
        (session / "session.json").write_text(json.dumps(configuration), encoding="ascii")
        (session / "disposable1.mcd").write_bytes(card((1, IV, slot("bof4", 2, 0x0805, node=0x800fae9c))))
        (session / "disposable2.mcd").write_bytes(card())
        service.journeys = {"bof4": {"reference": True, "campaign": {"route": "reference", "id": selected}}}
        with (patch("shell.service.runtime_reference_play.reference_status", return_value={"ready": True, "backend": "ref", "version": "test"}),
              patch("shell.service.runtime_linux.process_identity", return_value=None),
              patch("shell.service.runtime_setup._process_identity", return_value=None)):
            service.action("openGuide")
            self.assertEqual(service.snapshot()["guideStory"]["place"], "north-desert")
            legacy_scope = service.snapshot()["guideBranch"]
            self.assertEqual(legacy_scope, "lab/Original/reference/reference")
            family = "20261121T095900000000Z"
            (session / "session.json").write_text(json.dumps(configuration | {"guide_campaign": family}), encoding="ascii")
            # The previously selected receipt has since changed campaigns. Re-open must not reuse its old result.
            service.action("openGuide")
            self.assertEqual(service.snapshot()["guideStory"], {})
            selected_campaign = service._reference_campaign(
                "bof4", game_record, {"backend": "ref", "version": "test"}
            )
            self.assertEqual(selected_campaign["guideCampaign"], family)
            service.journeys["bof4"]["campaign"] = selected_campaign
            service.action("openGuide")
            family_scope = service.snapshot()["guideBranch"]
            self.assertEqual(family_scope, legacy_scope + "/" + family)
            self.assertEqual(service.snapshot()["guideStory"]["place"], "north-desert")
            service.process = object()
            service.guide_session.reading = True
            operation = {"game": "bof4", "channel": "lab", "backend": "reference", "route": "reference",
                         "guideCampaign": family, "paths": managed_cards.slot_paths(session), "lock": service._edition()}
            service.played_cards = operation
            service.action("openGuide")
            self.assertEqual(service.snapshot()["guideBranch"], family_scope)
            self.assertEqual(service.snapshot()["guideStory"]["place"], "north-desert")
            service.played_cards = operation | {"guideCampaign": "", "paths": {}}
            service.action("openGuide")
            self.assertEqual(service.snapshot()["guideBranch"], legacy_scope)
            self.assertEqual(service.snapshot()["guideStory"], {})
            service.process = service.played_cards = None
            service.guide_session.reading = False
            (session / "session.json").write_text(json.dumps(configuration | {"restored_branch": "d" * 32}), encoding="ascii")
            service.action("openGuide")
            self.assertEqual(service.snapshot()["guideStory"], {})
            service.journeys["bof4"]["campaign"]["id"] = "20261121T090000000000Z"
            service.action("openGuide")
            self.assertEqual(service.snapshot()["guideStory"], {})
