"""Integrity and offline reachability of the two published Field Guide volumes."""
import base64
import hashlib
import json
from pathlib import Path
import re
import unittest

from shell.guide_book import ART, CORE_PAGES, read_book


ROOT = Path(__file__).resolve().parents[1] / "design/field-guide"


class FieldGuideVolumeTests(unittest.TestCase):
    def test_books_have_complete_linked_routes_and_offline_sources(self):
        for game in CORE_PAGES:
            with self.subTest(game=game):
                book = read_book(ROOT / "wiki", game)
                self.assertGreaterEqual(len(book["route"]), 18)
                self.assertGreaterEqual(len(book["articles"]), 14)
                self.assertGreater(len({a["category"] for a in book["articles"]}), 2)
                for page in book["articles"] + book["route"]:
                    self.assertGreaterEqual(len(page["lead"].split()), 4, page["id"])
                    self.assertTrue(page["links"], page["id"])
                for stop in book["route"]:
                    self.assertGreaterEqual(len(stop["steps"]), 2, stop["id"])

    def test_manifest_describes_every_new_plate_and_exact_bytes(self):
        wiki = ROOT / "wiki"
        manifest = json.loads((wiki / "illustrations.json").read_text(encoding="utf-8"))
        plates = {p["id"]: p for s in manifest["sheets"] for p in s["plates"]}
        encoded = dict(re.findall(r"--art-([a-z0-9-]+): url\('data:image/webp;base64,([^']+)'\)",
                                  (wiki / "illustrations.css").read_text(encoding="ascii")))
        legacy = {"highlands", "sandsea", "flame", "frost", "thunder"}
        self.assertEqual(set(plates), (ART["bof3"] | ART["bof4"]) - legacy)
        self.assertEqual(plates.keys(), encoded.keys())
        for name, row in plates.items():
            with self.subTest(name=name):
                image = base64.b64decode(encoded[name], validate=True)
                self.assertEqual(image[8:12], b"WEBP")
                self.assertEqual(row["bytes"], len(image))
                self.assertEqual(row["sha256"], hashlib.sha256(image).hexdigest())
                self.assertTrue(row["description"])

    def test_atlas_record_reachability_and_spoiler_scope(self):
        for game in CORE_PAGES:
            book = read_book(ROOT / "wiki", game)
            articles = {page["id"]: page for page in book["articles"]}
            for stop in book["route"]:
                with self.subTest(game=game, stop=stop["id"]):
                    self.assertEqual(len(stop["steps"]), len(stop["landmarks"]))
                    for table in ("items", "encounters"):
                        if table in stop:
                            page = articles[stop["id"] + "-" + table]
                            self.assertEqual(stop["id"], page["unlock"])
                            self.assertEqual([stop["id"]], page["links"])
                            self.assertEqual(stop[table], page["records"])
                    if "map" in stop:
                        chart = stop["map"]
                        reached = {0}
                        for _ in chart["points"]:
                            for start, end in chart["paths"]:
                                if start in reached or end in reached:
                                    reached.update([start, end])
                        self.assertEqual(set(range(len(chart["points"]))), reached)
