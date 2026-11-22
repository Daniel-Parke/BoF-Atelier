"""Reader-facing invariants shared by the desktop book and the offline Field Guide."""
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from xml.etree import ElementTree

from shell.guide_book import read_book
from tools.bofkit import ATLAS_HASHES, KitError, inspect_public_file


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "design/field-guide"
BOOKS = {game: read_book(GUIDE / "wiki", game) for game in ("bof3", "bof4")}


class EditorialChecks(unittest.TestCase):
    def test_each_route_pin_opens_one_direction_and_each_local_record_has_a_subject(self):
        for book in BOOKS.values():
            for name, sheet in book["fieldSheets"].items():
                with self.subTest(game=book["game"], area=name):
                    svg = ElementTree.parse(GUIDE / "atlas" / sheet["map"])
                    pins = sorted(int(p.attrib["data-step"]) for p in svg.findall(".//*[@data-step]"))
                    self.assertEqual(pins, [s["key"] for s in sheet["steps"]])
                    self.assertTrue(sheet["mapAlt"].strip())
                    stop = next(s for s in book["route"] if s["id"] == sheet["stop"])
                    for key, prefix in (("items", "item."), ("encounters", "enemy.")):
                        for row in stop.get(key, []):
                            subject = book["entities"][prefix + row["name"].lower().strip()]
                            matches = [s for s in subject["observations"] if s["stop"] == stop["id"]
                                       and all(s[k] == v for k, v in row.items())]
                            self.assertTrue(matches, (subject["id"], row))
        dam = BOOKS["bof4"]["fieldSheets"]["dam"]
        self.assertIn("flywheel", " ".join(dam["opening"]["steps"]).lower())
        for name in ("Sluice Key", "Short Sword", "Swallow Eyes", "Vitamins"):
            self.assertIn(name, dam["warning"])
        self.assertFalse(BOOKS["bof4"]["fieldSheets"]["kurok"]["warning"])

    def test_full_teacher_rosters_units_and_wills(self):
        for game, roster in (("bof3", 17), ("bof4", 12)):
            book = BOOKS[game]
            self.assertEqual(len(book["teachers"]), roster)
            for teacher in book["teachers"]:
                page = next(p for p in book["articles"] if p["id"] == teacher["id"])
                self.assertEqual(page["referenceTables"][0]["rows"], [[l["goal"], l["skill"]] for l in teacher["lessons"]])
                self.assertEqual(len(page["referenceTables"][1]["rows"]), 6)
                if game == "bof4":
                    self.assertTrue(teacher["will"]["effect"].strip())
        rwolf = next(t for t in BOOKS["bof4"]["teachers"] if t["name"] == "Rwolf")
        self.assertEqual(rwolf["lessons"][-1], {"goal": "20 hits", "skill": "Flame Pillar"})

    def test_walkthroughs_give_readers_sources_they_can_find_again(self):
        for book in BOOKS.values():
            for stop in book["route"]:
                with self.subTest(game=book["game"], stop=stop["id"]):
                    citations = stop.get("sourceSections", [])
                    authors = {book["sources"][row["source"]]["title"].split(" · ", 1)[0].casefold()
                               for row in citations}
                    self.assertGreaterEqual(len(authors), 2, "Cite two independently authored accounts of this stop")
                    for row in citations:
                        self.assertIn(row["source"], stop["sources"])
                        self.assertTrue(row["section"].strip())

    def test_published_reader_copy_avoids_recurring_filler_and_authoring_notes(self):
        # These are known editorial regressions. Read the pages as well as running the check.
        filler = re.compile(r"\b(?:lorem ipsum|insert description here|as an ai|in this guide we will|"
                            r"embark on (?:a|an|your) (?:epic|unforgettable)|whether you.re a seasoned|"
                            r"unlock the secrets of|in the vibrant world of)\b", re.I)
        def text_values(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, list):
                for item in value:
                    yield from text_values(item)
            elif isinstance(value, dict):
                for key, item in value.items():
                    if key not in ("sources", "evidence", "url"):
                        yield from text_values(item)
        for book in BOOKS.values():
            for value in text_values(book):
                self.assertNotRegex(value, filler)

    def test_atlas_assets_match_exactly_and_corrupt_assets_stay_private(self):
        for name in ATLAS_HASHES:
            self.assertTrue(inspect_public_file(ROOT / name, Path(name)))
        with TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "substitute.webp"
            candidate.write_bytes(b"replaced")
            with self.assertRaises(KitError):
                inspect_public_file(candidate, Path("design/field-guide/atlas/kurok-wind.webp"))
