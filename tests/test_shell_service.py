"""No commercial fixtures or system controller are required by these tests."""

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from shell.native_input import Edges, DEFAULT
from shell.service import PlayerService
from shell.rulebook import Rulebook
from tools.campaigns import CampaignStore


class Pad:
    profile = "test device"
    handle = None
    name = "Keyboard"
    family = "position"
    raw = False
    error = ""
    devices = []
    last_input = ""
    device_id = 0

    def __init__(self):
        self.edges = Edges()

    def poll(self, *args):
        return None, None

    def close(self):
        pass


class ShellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = PlayerService(self.root, Pad())
        self.addCleanup(self.service.close)

    def finish(self):
        for _ in range(1200):
            self.service.poll()
            if self.service.worker is None:
                return
            time.sleep(0.01)
        self.fail("Local job did not finish")

    def test_clean_machine_and_title_preferences(self):
        self.assertEqual(self.service.snapshot()["primary"], "Add game archive")
        self.assertFalse(self.service.snapshot()["canLaunch"])
        self.service.action("selectGame", "bof4")
        self.service.action("tv")
        self.service.action("page", "Controls")
        reopened = PlayerService(self.root, Pad())
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.game, "bof4")
        self.assertTrue(reopened.snapshot()["tv"])
        self.assertEqual(reopened.page, "Journey")

    def test_guide_keys_persist_by_game_without_affecting_checkpoint_bindings(self):
        self.service.action("shortcutKey", {"action": "guide", "choice": "Ctrl+Shift+H"})
        self.service.action("shortcutPad", {"action": "guide", "choice": "none"})
        with self.assertRaisesRegex(ValueError, "free Field guide"):
            self.service.action("shortcutKey", {"action": "guide", "choice": "F2"})
        self.service.action("selectGame", "bof4")
        self.assertEqual(self.service.snapshot()["shortcuts"]["guide"]["key"], "Ctrl+Shift+G")
        self.service.action("selectGame", "bof3")
        reopened = PlayerService(self.root, Pad())
        self.addCleanup(reopened.close)
        shortcuts = reopened.snapshot()["shortcuts"]
        self.assertEqual(shortcuts["guide"]["key"], "Ctrl+Shift+H")
        self.assertEqual(shortcuts["guide"]["padChoice"], "none")
        self.assertEqual(shortcuts["quick"]["key"], "F2")

    def test_guide_scope_follows_the_actual_writable_branch(self):
        self.service.channel = "lab"
        self.service.runtime["can_launch"] = True
        base = self.service.snapshot()["guideBranch"]
        self.service.action("openGuide", "genes")
        self.assertEqual((self.service.page, self.service.guide_entry), ("Field guide", "genes"))
        self.service.played_cards = {"channel": "lab", "backend": "stock", "route": "stock"}
        self.assertEqual(self.service.snapshot()["guideBranch"], base)
        self.service.played_cards["route"] = "restored/branch-a"
        self.assertNotEqual(self.service.snapshot()["guideBranch"], base)
        self.service.process = object()
        with self.assertRaisesRegex(ValueError, "close it"):
            self.service.action("page", "Workshop")
        with self.assertRaisesRegex(ValueError, "close it"):
            self.service.action("shortcutPad", {"action": "guide", "choice": "none"})
        self.assertEqual(self.service.page, "Field guide")

    def test_unreadable_guide_setting_leaves_keyboard_recovery_available(self):
        self.service.settings["guide_shortcuts"] = {
            "bof3": {"key": [], "pads": {self.service.pad.profile: {"invalid": True}}}
        }
        guide = self.service.snapshot()["shortcuts"]["guide"]
        self.assertEqual((guide["key"], guide["padChoice"]), ("Ctrl+Shift+G", "auto"))

    def test_bad_import_and_firmware_return_to_usable_library(self):
        invalid = self.root / "bad.zip"
        invalid.write_bytes(b"not an archive")
        self.service.action("import", [str(invalid)])
        self.finish()
        self.assertIn("bad.zip", self.service.message)
        self.assertFalse(self.service.record)
        self.assertEqual(self.service.snapshot()["job"], {})
        self.service.action("firmware", str(invalid))
        self.finish()
        self.assertFalse(self.service.snapshot()["runtime"]["firmware_ready"])
        self.service.action("page", "Recovery")
        self.assertEqual(self.service.snapshot()["points"], [])

    def test_shortcut_keys_are_game_specific_and_reject_occupied_input(self):
        self.service.action("shortcutKey", {"action": "speed", "choice": "F7"})
        with self.assertRaisesRegex(ValueError, "input is already in use"):
            self.service.action("shortcutKey", {"action": "quick", "choice": "F7"})
        self.service.action("selectGame", "bof4")
        keys = self.service.snapshot()["shortcuts"]["quick"]
        self.assertEqual(keys["key"], "F7")
        self.assertNotIn("F2", keys["keys"])
        self.service.action("shortcutKey", {"action": "quick", "choice": "F4"})
        self.service.action("selectGame", "bof3")
        self.assertEqual(self.service.snapshot()["shortcuts"]["speed"]["key"], "F7")
        self.service.action("selectGame", "bof4")
        self.assertEqual(self.service.snapshot()["shortcuts"]["quick"]["key"], "F4")

    def test_rejects_unverified_launch_and_unscoped_files(self):
        with self.assertRaises(ValueError):
            self.service.action("launch")
        with self.assertRaises(ValueError):
            self.service.action("arbitrary command")
        with self.assertRaises(ValueError):
            self.service.action("restoreCards", "not-an-id")

    def test_reference_route_keeps_the_stock_iv_hold(self):
        self.service.game = "bof4"
        self.service.channel = "lab"
        self.service.runtime.update(can_launch=False, compatibility_blocked=True, reason="Stock timing hold")
        self.service.records = [{"id": "bof4", "verified": True, "cue": str(self.root / "iv.cue")}]
        with patch("shell.service.runtime_reference_play.reference_status", return_value={"ready": True}):
            state = self.service.snapshot()
            self.assertTrue(state["referenceReady"])
            self.assertFalse(state["canLaunch"])
            self.assertEqual(state["primary"], "Play in Redux Lab")
            self.assertTrue(state["runtime"]["compatibility_blocked"])
            self.service.channel = "play"
            self.assertFalse(self.service.snapshot()["referenceReady"])
            with self.assertRaisesRegex(ValueError, "Research Lab"):
                self.service.action("launchReference")

    def test_closed_save_restore_goes_to_separate_branch(self):
        source = self.root / "selected saves"
        source.mkdir()
        original = source / "example.mcd"
        original.write_bytes(b"original ordinary memory card fixture")
        self.service.action("capture", str(source))
        self.finish()
        point = self.service.snapshot()["points"][0]
        self.assertEqual(point["cards"], 1)
        self.service.action("restoreCards", point["id"])
        self.finish()
        restored = list((self.root / "lab/restored/bof3").glob("*/example.mcd"))
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0].read_bytes(), original.read_bytes())
        self.assertEqual(len(CampaignStore(self.root).history("bof3")), 1)

    def test_press_release_gate_and_directional_repeat(self):
        edges = Edges()
        self.assertEqual(edges.advance({"south"}, 1, DEFAULT), (None, None))
        edges.advance(set(), 1.1, DEFAULT)
        self.assertEqual(edges.advance({"south"}, 1.2, DEFAULT), ("select", "south"))
        self.assertEqual(edges.advance({"south"}, 1.9, DEFAULT), (None, None))
        edges.reset()
        self.assertEqual(edges.advance({"south"}, 2, DEFAULT), (None, None))
        edges.advance(set(), 2.1, DEFAULT)
        self.assertEqual(edges.advance({"up"}, 2.2, DEFAULT), ("up", "up"))
        self.assertEqual(edges.advance({"up"}, 2.9, DEFAULT), ("up", None))

    def test_rulebook_choices_limit_genes_and_remember_hidden_names(self):
        third = Rulebook(
            {
                "game": "bof3",
                "costs": bytes(range(18)),
                "recipes": bytes([10, 11, 12]) * 11,
                "groups": bytes(11),
            }
        )
        for gene in (1, 2, 3):
            third.apply(gene)
        self.assertIn("Initial AP 6.", third.model()["summary"])
        self.assertEqual(third.model()["controls"][2]["ap"], 2)
        self.assertEqual(third.model()["controls"][1]["label"], "Gene 01")
        third.apply("names")
        self.assertEqual(third.model()["controls"][1]["label"], "Frost")
        with self.assertRaisesRegex(ValueError, "Remove one"):
            third.apply(4)
        fourth = Rulebook({"game": "bof4", "masters": bytes(range(78))})
        fourth.apply(3)
        self.assertIn("Master 00 → Master 02", fourth.model()["summary"])
        fourth.apply({"compare": "first", "id": 1})
        self.assertEqual(fourth.model()["stats"][0],
                         {"label": "HP", "first": 6, "second": 12, "difference": 6})

    def test_mapping_preview_timeout_and_duplicate_swap(self):
        with patch("shell.service.time.monotonic", return_value=5):
            self.service.proposed_binding = ["select", "east"]
            self.service.binding_deadline = 10
            self.service.action("acceptBinding")
        settings = json.loads((self.root / "atelier/player-settings.json").read_text())
        mapping = settings["bindings"][Pad.profile]
        self.assertEqual((mapping["select"], mapping["back"]), ("east", "south"))
        self.service.proposed_binding = ["back", "west"]
        self.service.binding_deadline = 0
        self.service.poll()
        self.assertIsNone(self.service.proposed_binding)
        self.assertEqual(mapping["back"], "south")

    def test_gameplay_remap_keeps_launcher_confirm_unchanged(self):
        with patch("shell.service.time.monotonic", return_value=5):
            self.service.proposed_binding = ["game:Cross", "west"]
            self.service.binding_deadline = 10
            self.service.action("acceptBinding")
        settings = json.loads((self.root / "atelier/player-settings.json").read_text())
        mapping = settings["gameplay_bindings"][Pad.profile]
        self.assertEqual((mapping["Cross"], mapping["Square"]), ("west", "south"))
        self.assertEqual(self.service.snapshot()["input"]["bindings"]["select"], "south")

    def test_restore_state_only_is_never_offered_as_ordinary_save(self):
        source = self.root / "copies"
        source.mkdir()
        (source / "one.state").write_bytes(b"state")
        point = CampaignStore(self.root).capture(
            "bof3", source, {"profile": "isolated"}, closed=True
        )
        self.service.refresh()
        self.assertEqual(self.service.snapshot()["points"][0]["cards"], 0)
        with self.assertRaises(ValueError):
            self.service.action("restoreCards", point["id"])

    def test_receipt_cannot_point_outside_library(self):
        d = self.root / "games/bof3"
        d.mkdir(parents=True)
        (d / "import-receipt.json").write_text(
            json.dumps({"library_id": "bof3", "working_cue": "../other.cue"})
        )
        self.service.refresh()
        self.assertFalse(self.service.snapshot()["canLaunch"])
        self.assertTrue(self.service.message)

    def test_archive_with_several_firmwares_requires_explicit_member(self):
        choices = [
            {"name": "First", "region": "NTSC-U", "member": "one/rom.bin"},
            {"name": "Second", "region": "NTSC-U", "member": "two/rom.bin"},
        ]
        with (
            patch(
                "shell.service.firmware.firmware_choices",
                return_value=choices,
                create=True,
            ),
            patch("shell.service.runtime_setup.import_firmware") as accept,
        ):
            selected = self.root / "selected.zip"
            self.service.action("firmware", str(selected))
            self.finish()
            accept.assert_not_called()
            self.assertEqual(len(self.service.snapshot()["firmwareChoices"]), 2)
            self.service.action("firmwareMember", "two/rom.bin")
            self.finish()
            accept.assert_called_once_with(self.root, selected, "play", "two/rom.bin")
            self.assertEqual(self.service.snapshot()["firmwareChoices"], [])

    def test_unreadable_preferences_are_preserved_before_using_defaults(self):
        directory = self.root / "atelier"
        directory.mkdir(exist_ok=True)
        path = directory / "player-settings.json"
        path.write_text("{broken", encoding="utf-8")
        reopened = PlayerService(self.root, Pad())
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.snapshot()["title"], "Breath of Fire III")
        self.assertIn("preferences", reopened.message)
        reopened.action("tv")
        self.assertEqual(
            next(directory.glob("player-settings-unreadable-*.json")).read_text(),
            "{broken",
        )
        path.write_text(json.dumps({"bindings": {"any": ["bad"]}}), encoding="utf-8")
        reopened._load_preferences()
        self.assertEqual(reopened.snapshot()["input"]["bindings"], DEFAULT)

    def test_one_damaged_receipt_keeps_the_other_game_available(self):
        for game in ("bof3", "bof4"):
            directory = self.root / "games" / game
            directory.mkdir(parents=True)
            receipt = directory / "import-receipt.json"
            if game == "bof3":
                receipt.write_text("unreadable")
                continue
            (directory / "disc.cue").write_text("track")
            receipt.write_text(
                json.dumps(
                    {
                        "game": game,
                        "library_id": game,
                        "working_cue": "disc.cue",
                        "tracks": [{}],
                        "seed_entry_hashes_match": True,
                        "content_fingerprint": "a" * 64,
                    }
                )
            )
        self.service.action("selectGame", "bof4")
        self.assertEqual(self.service.record["id"], "bof4")
        self.assertIn("bof3", self.service.message)
        snapshot = self.service.snapshot()
        self.assertEqual(snapshot["primary"], "Open Workshop")
        self.assertEqual(snapshot["homeHeading"], "Playback on hold")
        self.assertIn("track 2", snapshot["runtime"]["reason"])
        with self.assertRaisesRegex(ValueError, "track 2"):
            self.service.action("launch")


if __name__ == "__main__":
    unittest.main()
