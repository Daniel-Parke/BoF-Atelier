import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import checkpoints, runtime_input


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.state = self.root / "state.sav"
        self.identity = {"runtime": "locked", "firmware": "firmware", "cue": "cue"}
        self.state.write_bytes(b"synthetic state")

    def capture(self, kind="suspend", before=None):
        return checkpoints.capture(
            self.root, "bof3", kind, self.state, before, self.identity, {"1": "original"}, {},
        )

    def load(self, kind="suspend", *, identity=None, cards=None):
        return checkpoints.load(self.root, "bof3", kind, identity or self.identity, cards or {"1": "original"})

    def test_unchanged_runtime_slot_cannot_replace_a_checkpoint(self):
        self.assertTrue(self.capture())
        self.state.write_bytes(b"another session")
        self.assertFalse(self.capture(before=checkpoints.file_stamp(self.state)))
        self.assertEqual(self.load().state, b"synthetic state")

    def test_quick_and_suspend_are_independent(self):
        self.assertTrue(self.capture("quick"))
        self.state.write_bytes(b"suspended later")
        self.assertTrue(self.capture("suspend"))
        self.assertEqual(self.load("quick").state, b"synthetic state")
        self.assertEqual(self.load().state, b"suspended later")

    def test_runtime_and_ordinary_save_mismatches_reject_the_state(self):
        self.capture()
        with self.assertRaisesRegex(ValueError, "runtime or campaign"):
            self.load(identity=self.identity | {"runtime": "different"})
        with self.assertRaisesRegex(ValueError, "runtime or campaign"):
            self.load(cards={"1": "ordinary progression"})

    def test_corruption_or_unknown_receipt_fails_closed(self):
        self.capture()
        target = checkpoints.path_for(self.root, "bof3", "suspend")
        raw = target.read_bytes()
        target.write_bytes(raw[:-1] + b"!")
        with self.assertRaisesRegex(ValueError, "failed verification"):
            self.load()
        header, payload = raw.split(b"\n", 1)
        target.write_bytes(json.dumps(json.loads(header) | {"format": 200}).encode() + b"\n" + payload)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.load()

    def test_failed_publication_leaves_previous_checkpoint_playable(self):
        self.capture()
        self.state.write_bytes(b"new checkpoint")
        with patch.object(checkpoints, "atomic_bytes", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.capture()
        self.assertEqual(self.load().state, b"synthetic state")


class ShortcutTests(unittest.TestCase):
    def test_free_stick_defaults_to_quick_save_or_enabled_hold_speed(self):
        defaults = runtime_input.GAMEPLAY_DEFAULTS
        keys = runtime_input.SHORTCUT_KEYS | {"speed": "F7"}
        bindings = runtime_input.shortcut_bindings(keys, {}, defaults, False)
        self.assertEqual(bindings["quick"], ["Keyboard/F2", "SDL-0/LeftStick"])
        self.assertEqual(bindings["suspend"], ["Keyboard/F9"])
        bindings = runtime_input.shortcut_bindings(keys, {}, defaults, True)
        self.assertEqual(bindings["speed"], ["Keyboard/F7", "SDL-0/LeftStick"])
        self.assertEqual(bindings["quick"], ["Keyboard/F2"])

    def test_explicit_shortcut_has_priority_and_cannot_take_gameplay_or_pause(self):
        keys = runtime_input.SHORTCUT_KEYS
        defaults = runtime_input.GAMEPLAY_DEFAULTS
        bindings = runtime_input.shortcut_bindings(keys, {"quick": "left stick"}, defaults, True)
        self.assertIn("SDL-0/LeftStick", bindings["quick"])
        self.assertNotIn("SDL-0/LeftStick", bindings["speed"])
        mapping = runtime_input.resolve_gameplay({"Cross": "left stick"})
        bindings = runtime_input.shortcut_bindings(keys, {"speed": "left stick", "suspend": "right stick"}, mapping, True)
        self.assertEqual(bindings["speed"], ["Keyboard/Tab"])
        self.assertEqual(bindings["suspend"], ["Keyboard/F9"])
        self.assertIn("SDL-0/A", bindings["quick"])
