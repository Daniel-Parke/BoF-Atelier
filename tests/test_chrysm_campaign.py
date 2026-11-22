"""Regressions for the Campaign resume decision and opt-in menu music."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from shell.menu_sound import MenuSound
from shell.service import PlayerService
from tools import checkpoints
from test_shell_service import Pad
from tempfile import TemporaryDirectory


class CampaignTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = PlayerService(self.root, Pad(), channel="lab")
        self.addCleanup(self.service.close)

    def test_ordinary_campaign_takes_precedence_over_a_different_suspend(self):
        service = self.service
        service.records = [{"id": "bof3", "fingerprint": "a"*64, "cue": str(self.root / "fixture.cue"), "verified": True}]
        service.journeys = {"bof3": {"labStock": True}}
        service.runtime.update(version="test", firmware_sha256="firmware")
        state = self.root / "fixture.state"
        state.write_bytes(b"synthetic emulator checkpoint")
        identity = {"runtime": "test"}
        checkpoints.capture(self.root, "bof3", "suspend", state, None, identity, {}, {})
        with (patch("shell.service.sys.platform", "win32"),
              patch("shell.checkpoint_session.identity", return_value=identity),
              patch("shell.service.managed_cards.duckstation_paths", return_value={}),
              patch("shell.service.managed_cards.read_cards") as read):
            read.return_value = SimpleNamespace(title="", slots={})
            self.assertTrue(service._compatible_suspend())
            read.return_value = SimpleNamespace(title="Another campaign", slots={1: b"changed card"})
            self.assertFalse(service._compatible_suspend())
            service.channel = "play"
            self.assertFalse(service._compatible_suspend())

    def test_ambient_preferences_persist_and_start_quiet(self):
        self.assertFalse(self.service.snapshot()["preferences"]["menuMusic"])
        self.service.action("menuMusic", True)
        self.service.action("menuVolume", 35)
        self.service.action("reduceMotion", True)
        reopened = PlayerService(self.root, Pad(), channel="lab")
        self.addCleanup(reopened.close)
        prefs = reopened.snapshot()["preferences"]
        self.assertEqual((prefs["menuMusic"], prefs["menuVolume"], prefs["reduceMotion"]), (True, 35, True))

    def test_audio_stops_before_game_and_focus_loss_and_rotates_menu_cues(self):
        music = MenuSound(self.root)
        self.service.focus = True
        music.update(self.service, audible=True)
        self.assertIsNone(music.player)
        music.player = MagicMock()
        self.service.action("menuMusic", True)
        music.update(self.service, audible=True)
        first = music.previous["bof3"]
        self.service.starting_game = True
        music.update(self.service, audible=True)
        music.player.stop.assert_called_once()
        self.service.starting_game = False
        music.update(self.service, audible=True)
        self.assertNotEqual(first, music.previous["bof3"])
        self.service.focus = False
        music.update(self.service, audible=True)
        self.assertIsNone(music.current_game)
        self.assertEqual(music.player.play.call_count, 2)
