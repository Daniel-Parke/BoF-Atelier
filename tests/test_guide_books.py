"""Integrity and offline reachability of the two published Field Guide volumes."""
import base64
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from shell.guide_book import ART, CORE_PAGES, read_book


ROOT = Path(__file__).resolve().parents[1] / "design/field-guide"


class FieldGuideVolumeTests(unittest.TestCase):
    def test_damaged_document_has_a_volume_error_at_any_level(self):
        with TemporaryDirectory() as folder:
            target = Path(folder) / "bof3.json"
            volume = json.loads((ROOT / "wiki/bof3.json").read_bytes())
            volume["sources"][next(iter(volume["sources"]))] = []
            for broken in ([], None, volume, {"game": "bof3", "version": 2}):
                with self.subTest(shape=type(broken).__name__):
                    target.write_text(json.dumps(broken), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "bof3 Field Guide"):
                        read_book(target.parent, "bof3")

    def test_published_first_format_and_unsupported_versions(self):
        with TemporaryDirectory() as folder:
            data = json.loads((ROOT / "wiki/bof4.json").read_bytes())
            data["version"] = 1
            stop = next(s for s in data["route"] if s["id"] == "dam-kyria")
            first_edition_maps = {1110, 1024, 1029, 1028, 4097, 1043, 1045, 1046}
            stop["floors"] = [floor for floor in stop["floors"] if floor["mapId"] in first_edition_maps]
            parts = stop["sectionsByArea"]
            # The first edition grouped the village and woods under the name Kyria.
            parts[-2]["endStep"] = parts[-1]["endStep"]
            parts.pop()
            for part in parts:
                part.pop("id")
                part.pop("floorIds")
            for row in stop["items"] + stop["encounters"]:
                row.pop("areaIds")
            del data["fieldSheets"]["kyria-woods"]
            del data["fieldSheets"]["kyria"]
            del data["fieldSheets"]["kyria-passage"]
            next(s for s in data["route"] if s["id"] == "synesta").pop("sectionsByArea")
            data["fieldSheets"]["dam"].pop("nextSheet")
            for row in [*data["articles"], *data["route"]]:
                row["links"] = [key for key in row["links"] if key not in ("kyria-woods","kyria","kyria-passage")]
            target = Path(folder) / "bof4.json"
            target.write_text(json.dumps(data), encoding="utf-8")
            restored = read_book(target.parent,"bof4")
            local = next(s for s in restored["route"] if s["id"] == "dam-kyria")
            self.assertEqual([4097,1043,1045,1046],local["sectionsByArea"][-1]["floorIds"])
            data["version"] = 99
            target.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"Unsupported bof4 Field Guide version 99"):
                read_book(target.parent,"bof4")

    def test_passage_observations_unlock_before_the_town(self):
        book = read_book(ROOT / "wiki", "bof4")
        passage = book["fieldSheets"]["kyria-passage"]
        self.assertEqual(("synesta", "dam-kyria"), (passage["stop"], passage["unlock"]))
        for key in ("item.ammonia", "enemy.army bat"):
            sightings = book["entities"][key]["observations"]
            cave = [s for s in sightings if "kyria-passage" in s.get("areaIds", [])]
            town = [s for s in sightings if "synesta" in s.get("areaIds", [])]
            self.assertTrue(cave and town, key)
            self.assertTrue(all(s["unlock"] == "dam-kyria" for s in cave))
            self.assertTrue(all(s.get("unlock", s["stop"]) == "synesta" for s in town))

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
