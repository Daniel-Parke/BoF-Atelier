"""Local service shared by both desktop comparisons. No network listener."""

from __future__ import annotations

from collections.abc import Callable
import json
import base64
import hashlib
import re
import sqlite3
import os
from pathlib import Path
import queue
import sys
import threading
import time

from tools import campaigns, checkpoints, firmware, guide_story, import_games, managed_cards, memory_card, runtime_setup, workshop_assets
from tools.local_store import atomic_bytes, canonical_bytes, member_path, plain_path
from shell.native_input import DEFAULT, NativeInput
from shell.guide_session import GuideSession
from shell.rulebook import Rulebook
from shell import checkpoint_session, session
from tools import guide_visits, progression
from tools import edition_session, runtime_linux, runtime_reference_play
from tools.redux_checkpoints import SCANCODES as REDUX_SHORTCUT_KEYS
from tools.runtime_input import (
    GAMEPLAY_DEFAULTS, HOST_BUTTONS, PAUSE_BUTTON, REMAPPABLE_KEYS, SHORTCUT_KEYS,
    GUIDE_KEYS, guide_binding, resolve_gameplay, shortcut_bindings, stock_guide_occupied,
)
from uuid import uuid4


TITLES = {"bof3": "Breath of Fire III", "bof4": "Breath of Fire IV"}
PAGES = ("Journey", "Field guide", "Library & setup", "Controls", "Recovery", "Workshop", "Lab")


def default_library() -> Path:
    if sys.platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
            / "BoF Atelier"
            / "Library"
        )
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/BoF Atelier/Library"
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        / "bof-atelier/library"
    )


def read_object(path: Path, limit: int = 256 * 1024) -> dict:
    path = plain_path(path)
    if not path.exists():
        return {}
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError(f"{path.name} is too large or unavailable.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} is invalid.")
    return value


def library_records(root: Path, issues: list[str]) -> list[dict]:
    base = plain_path(root / "games")
    if not base.exists():
        return []
    records = []
    for index, directory in enumerate(base.iterdir()):
        if index > 500:
            raise ValueError("Choose a library with fewer than 500 disc revisions.")
        if directory.name.startswith(".") or not directory.is_dir():
            continue
        try:
            receipt = read_object(directory / "import-receipt.json", 4 * 1024**2)
            if not receipt:
                continue
            if receipt.get("library_id") != directory.name or not isinstance(
                receipt.get("tracks"), list
            ):
                raise ValueError(
                    "The import receipt is inconsistent. Re-import the original archive."
                )
            cue = plain_path(directory / member_path(receipt["working_cue"]))
        except (OSError, TypeError, ValueError, KeyError) as exc:
            issues.append(f"{directory.name}: {exc}")
            continue
        records.append(
            {
                "id": directory.name,
                "game": receipt.get("game"),
                "serial": receipt.get("serial", ""),
                "tracks": len(receipt.get("tracks", [])),
                "fingerprint": receipt.get("content_fingerprint", ""),
                "verified": bool(receipt.get("seed_entry_hashes_match"))
                and cue.is_file(),
                "reference": bool(receipt.get("reference_match")),
                "cue": str(cue),
            }
        )
    return sorted(records, key=lambda row: row["id"])


class PlayerService:
    def __init__(
        self,
        library: Path | None = None,
        controller=None,
        *,
        channel: str | None = None,
    ):
        self.home = default_library()
        self.remember_library = library is None
        self.selection_file = self.home.parent / "selected-library.json"
        self.message = ""
        if library is not None:
            self.root = plain_path(library)
        else:
            try:
                self.root = plain_path(
                    read_object(self.selection_file).get("path") or self.home
                )
            except (OSError, TypeError, ValueError):
                self.root = plain_path(self.home)
                self.message = "The saved library location could not be opened. Choose its folder in Library & setup."
        self.pad = controller if controller is not None else NativeInput()
        self.events = queue.SimpleQueue()
        self.worker = None
        self.process = None
        self.player_hwnd = 0
        self.guide_session = GuideSession()
        self.guide_request = 0
        self.guide_entry = "guide"
        self.guide_error = ""
        self.guide_story = {}
        self.played_cards = None
        self.next_visit_sample = 0.0
        self.starting_game = False
        self.cancel = threading.Event()
        self.focus = True
        self.capture_action = ""
        self.proposed_binding = None
        self.binding_deadline = 0
        self.discovered = []
        self.firmware_source = None
        self.firmware_members = []
        self.version = 0
        self.released_to_runtime = False
        self.job = {}
        self.outcome = {}
        self.journeys = {}
        self.records = []
        self.history = []
        self.workshop = {}
        self.rulebooks = {}
        self.settings = {}
        self._load_preferences()
        if channel in ("play", "lab"):
            self.channel = channel
        self.refresh()

    def _load_preferences(self):
        self.settings_damaged = False
        try:
            self.settings = read_object(self.root / "atelier/player-settings.json")
        except (OSError, ValueError):
            self.settings = {}
            self.settings_damaged = True
            self.message = "Saved Player preferences were unreadable. Keyboard defaults are available."
        self.game = self.settings.get("game", "bof3")
        if not isinstance(self.game, str) or self.game not in TITLES:
            self.game = "bof3"
        self.channel = self.settings.get("channel", "play")
        if self.channel not in ("play", "lab"):
            self.channel = "play"
        bindings = self.settings.get("bindings", {})
        if not isinstance(bindings, dict) or any(
            not isinstance(mapping, dict)
            or any(
                k not in DEFAULT or not isinstance(v, str) for k, v in mapping.items()
            )
            for mapping in bindings.values()
        ):
            self.settings_damaged = True
            self.message = "Saved controller bindings were unreadable. The default mapping is active."
            bindings = {}
        self.settings["bindings"] = bindings
        gameplay = self.settings.get("gameplay_bindings", {})
        try:
            if not isinstance(gameplay, dict):
                raise ValueError("Gameplay mappings must be grouped by controller.")
            for mapping in gameplay.values():
                if not isinstance(mapping, dict) or not all(isinstance(v, str) for v in mapping.values()):
                    raise ValueError("Gameplay mapping is invalid.")
                resolve_gameplay(mapping)
        except ValueError:
            self.settings_damaged = True
            self.message = "Saved gameplay mappings were unreadable. Default controls are available."
            gameplay = {}
        self.settings["gameplay_bindings"] = gameplay
        self.page = "Journey"

    def _save(self):
        if self.settings_damaged:
            path = plain_path(self.root / "atelier/player-settings.json")
            if path.stat().st_size > 256 * 1024:
                raise ValueError(
                    "The existing preferences require inspection before they can be replaced."
                )
            backup = path.with_name(
                "player-settings-unreadable-"
                + hashlib.sha256(path.read_bytes()).hexdigest()
                + ".json"
            )
            if not backup.exists():
                atomic_bytes(backup, path.read_bytes())
            self.settings_damaged = False
        self.settings.update(game=self.game, channel=self.channel)
        atomic_bytes(
            self.root / "atelier/player-settings.json", canonical_bytes(self.settings)
        )

    def refresh(self):
        self.guide_story = {}
        self.campaign_story = {}
        self.suspend_ready = False
        self.records, self.history, self.workshop = [], [], {}
        self.restored = []
        self.art = {}
        for game in (*TITLES, "bof3-original", "bof3-crisp"):
            try:
                local = plain_path(self.root / "atelier/library-art" / (game + ".png"))
                if local.is_file() and local.stat().st_size <= 4 * 1024**2:
                    self.art[game] = local.as_uri()
            except (OSError, ValueError):
                continue
        self.journeys = {}
        self.runtime = {
            "runtime_ready": False,
            "firmware_ready": False,
            "can_launch": False,
            "reason": "Unavailable",
            "version": "",
            "running": False,
        }
        try:
            issues = []
            self.records = library_records(self.root, issues)
            if issues:
                self.message = "\n".join(issues)
            self.runtime = runtime_setup.game_launch_status(
                self.root, self.game, self.channel
            )
            self.journeys = {
                game: self._journey(game, self.runtime if game == self.game else
                                    runtime_setup.game_launch_status(self.root, game, self.channel))
                for game in TITLES
            }
            if (self.root / "atelier/campaigns.sqlite3").is_file():
                self.history = campaigns.CampaignStore(self.root).history(self.game)
            self.restored = self._restored(self.game)
            self.suspend_ready = self._compatible_suspend()
            if self.process is None:
                self.campaign_story = self._saved_guide_story()
            if self.record and re.fullmatch("[a-f0-9]{64}", self.record["fingerprint"]):
                folder = (
                    self.root
                    / "lab/workshop-assets"
                    / self.game
                    / ("v1-" + self.record["fingerprint"])
                )
                catalogue = read_object(folder / "catalogue.json", 16 * 1024**2)
                if catalogue:
                    self.workshop = {
                        "summary": catalogue.get("summary", {}),
                        "previews": catalogue.get("previews", []),
                        "folder": str(folder),
                    }
        except (
            OSError,
            TypeError,
            ValueError,
            KeyError,
            RuntimeError,
            sqlite3.DatabaseError,
        ) as err:
            self.message = str(err)
        self.version += 1

    def _compatible_suspend(self):
        """Offer direct resume only for the same verified edition and ordinary card."""
        if (self.channel != "lab" or sys.platform != "win32" or not self.record or not self.record["verified"]
                or not checkpoints.path_for(self.root, self.game, "suspend").is_file()):
            return False
        journey = self.journeys[self.game]
        cue = Path(self.record["cue"])
        lock = self._edition()
        try:
            if self.game == "bof3" and journey["labStock"]:
                mode = "stock"
                paths = managed_cards.duckstation_paths(self.root, "lab", self.game, cue)
                lock.update(runtime=self.runtime["version"], firmware=self.runtime.get("firmware_sha256", ""),
                            backend="duckstation")
            elif self.game == "bof4" and journey["reference"] and not journey["stock"]:
                mode = "reference"
                status = runtime_reference_play.reference_status(self.root, self.game)
                lock.update(runtime=status["version"], backend=status["backend"],
                            firmware=runtime_setup._catalogue()["openbios-psx-rom"]["member"]["sha256"])
                campaign = journey["campaign"]
                paths = (managed_cards.slot_paths(self.root / "lab/reference-play" / self.game / campaign["id"])
                         if campaign and campaign["route"] == "reference" else {})
            else:
                return False
            ordinary = managed_cards.read_cards(self.game, paths)
            anchor = checkpoints.card_identity(ordinary.slots) if ordinary.title else {}
            identity = checkpoint_session.identity(self.root, self.game, self.record, mode, lock)
            checkpoints.load(self.root, self.game, "suspend", identity, anchor)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            return False
        return True

    def _closed_reference_paths(self, directory, receipt, game, status, cue_digest, firmware_digest, restored_branch):
        if (receipt.get("backend") != status["backend"] or receipt.get("game") != game
                or receipt.get("restored_branch") != restored_branch
                or receipt.get("version") != status["version"] or receipt.get("cue_sha256") != cue_digest
                or receipt.get("firmware_sha256") != firmware_digest):
            return {}
        pid = receipt.get("pid")
        if type(pid) is not int or "created" not in receipt:
            return {}
        identity = (runtime_linux.process_identity if sys.platform.startswith("linux")
                    else runtime_setup._process_identity)
        running = identity(pid)
        if running and running[1] == receipt["created"]:
            return {}
        return managed_cards.slot_paths(directory)

    def _reference_campaign(self, game, record, status, restored_branch=None):
        folder = plain_path(self.root / "lab/reference-play" / game)
        if not folder.is_dir():
            return None
        cue_digest = runtime_setup._digest(Path(record["cue"]))
        firmware_digest = runtime_setup._catalogue()["openbios-psx-rom"]["member"]["sha256"]
        previous = [p for p in folder.iterdir() if re.fullmatch(r"\d{8}T\d{12}Z", p.name)]
        for directory in sorted(previous, reverse=True):
            try:
                receipt = read_object(directory / "session.json")
                paths = self._closed_reference_paths(
                    directory, receipt, game, status, cue_digest, firmware_digest, restored_branch
                )
                cards = managed_cards.read_cards(game, paths)
                if len(cards.slots) == 2 and cards.title:
                    return {"id": directory.name, "title": cards.title, "route": "reference",
                            "guideCampaign": runtime_reference_play.reading_campaign(receipt, directory.name)}
            except (OSError, ValueError, TypeError, KeyError):
                continue
        return None

    def _stock_campaign(self, game, cue, channel):
        try:
            paths = managed_cards.duckstation_paths(self.root, channel, game, Path(cue))
            title = managed_cards.read_cards(game, paths).title
            return {"title": title, "route": "stock"} if title else None
        except (OSError, ValueError, RuntimeError):
            return None

    def _restored(self, game):
        folder = plain_path(self.root / "lab/restored" / game)
        if not folder.is_dir():
            return []
        copies = []
        for branch in folder.iterdir():
            if not re.fullmatch(r"[0-9a-f]{32}", branch.name):
                continue
            try:
                receipt = read_object(branch / "branch.json")
                if (receipt.get("id"), receipt.get("game"), receipt.get("channel"), receipt.get("cards_only")) != (
                    branch.name, game, "lab", True
                ):
                    continue
                card = managed_cards.restored_cards(branch, receipt)
                if card.title:
                    copies.append({"id": branch.name, "title": card.title,
                                   "created": plain_path(branch / "branch.json").stat().st_mtime_ns})
            except (OSError, ValueError, RuntimeError, KeyError):
                continue
        return sorted(copies, key=lambda copy: copy["created"], reverse=True)[:100]

    def _journey(self, game, runtime):
        record = next((row for row in self.records if row["id"] == game), None)
        imported = record or next((row for row in self.records if row["game"] == game), None)
        verified = bool(record and record["verified"])
        result = {"archive": bool(imported), "verified": verified, "runtime": bool(runtime.get("runtime_ready")),
                  "firmware": bool(runtime.get("firmware_ready")), "stock": False, "reference": False,
                  "labStock": False, "campaign": None, "stockCampaign": None, "reason": runtime.get("reason", "")}
        entry = runtime_setup._component("duckstation", self.channel)
        result["cachedPackage"] = runtime_setup._archive(self.root, "duckstation", entry).is_file()
        if not imported:
            return result | {"step": "archive", "label": "Archive needed"}
        if not verified:
            return result | {"step": "revision", "label": "Archive needs review"}
        reference = runtime_reference_play.reference_status(self.root, game)
        result["reference"] = reference["ready"]
        result["stock"] = bool(runtime["can_launch"])
        result["labStock"] = game == "bof3" and bool(
            (runtime if self.channel == "lab" else runtime_setup.game_launch_status(self.root, game, "lab"))["can_launch"]
        )
        if result["stock"]:
            result["stockCampaign"] = self._stock_campaign(game, record["cue"], self.channel)
        if result["labStock"]:
            result["campaign"] = (result["stockCampaign"] if self.channel == "lab" else
                                  self._stock_campaign(game, record["cue"], "lab"))
        if result["reference"] and not result["campaign"]:
            result["campaign"] = self._reference_campaign(game, record, reference)
        if result["stock"]:
            return result | {"step": "ready", "label": "Ready to play"}
        if runtime.get("compatibility_blocked"):
            return result | {"step": "options", "label": "Lab available" if result["reference"] else "Playback route needed"}
        if not result["runtime"]:
            return result | {"step": "runtime", "label": "Playback setup needed"}
        if not result["firmware"]:
            return result | {"step": "bios", "label": "BIOS needed"}
        return result | {"step": "options", "label": "Playback needs attention"}

    @property
    def record(self):
        return next((row for row in self.records if row["id"] == self.game), None)

    def _edition(self):
        return {
            "profile": "Original",
            "game": self.game,
            "content": (self.record or {}).get("fingerprint", "unidentified"),
            "runtime": self.runtime.get("version", ""),
            "firmware": self.runtime.get("firmware_sha256", ""),
            "source": "user-selected closed folder",
            "state_compatibility": "unqualified",
        }

    def _available_shortcut_keys(self, action):
        if self.game == "bof4":
            return tuple(REDUX_SHORTCUT_KEYS) if action != "speed" else ("Tab",)
        return tuple(key for key in REMAPPABLE_KEYS if key != "Tab" or action == "speed")

    def _shortcut_keys(self):
        defaults = SHORTCUT_KEYS | ({"quick": "F7"} if self.game == "bof4" else {})
        profiles = self.settings.get("shortcut_keys")
        saved = profiles.get(self.game) if isinstance(profiles, dict) else None
        if isinstance(saved, dict) and saved.keys() == defaults.keys() and all(
            key in self._available_shortcut_keys(action) for action, key in saved.items()
        ) and len(set(saved.values())) == len(saved):
            return dict(saved)
        return defaults

    def _shortcut_pads(self):
        profiles = self.settings.get("shortcut_pads")
        saved = profiles.get(self.pad.profile) if isinstance(profiles, dict) else None
        valid = {"none", "auto", *HOST_BUTTONS}
        if isinstance(saved, dict) and all(isinstance(value, str) and value in valid for value in saved.values()):
            return saved
        return {}

    def _guide_binding(self, gameplay, *, for_launch=False, reference=False, checkpoints_enabled=False):
        profiles = self.settings.get("guide_shortcuts", {})
        profile = profiles.get(self.game, {}) if isinstance(profiles, dict) else {}
        if not isinstance(profile, dict):
            profile = {}
        pads = profile.get("pads")
        choice = pads.get(self.pad.profile, "auto") if isinstance(pads, dict) else "auto"
        if not isinstance(choice, str):
            choice = "auto"
        available = getattr(self.pad, "available_buttons", None) if self.pad.handle else None
        if not self.pad.handle and not for_launch:
            available = ()
        navigation = DEFAULT | self.settings["bindings"].get(self.pad.profile, {})
        occupied = ()
        if gameplay is not None and not reference:
            try:
                directory = runtime_setup._installation(self.root, "lab", "duckstation")
                occupied = stock_guide_occupied(directory, self.game, checkpoints=checkpoints_enabled,
                                                fast=self.settings.get("bof3_hold_2x") is True)
            except (OSError, ValueError, runtime_setup.RuntimeSetupError):
                gameplay = None
        return guide_binding(profile.get("key", GUIDE_KEYS[0]), choice, gameplay,
                             self._shortcut_pads(), available, navigation=navigation.values(),
                             reference=reference, runtime_buttons=occupied)

    def _guide_branch(self):
        operation = self.played_cards
        if operation:
            route = operation["route"]
            if route == "reference" and operation.get("guideCampaign"):
                route += "/" + operation["guideCampaign"]
            return "/".join((operation["channel"], "Original", operation["backend"], route))
        journey = self.journeys.get(self.game, {})
        if self.runtime.get("can_launch"):
            channel, route = self.channel, "stock"
        else:
            channel = "lab" if journey.get("reference") or journey.get("labStock") else self.channel
            route = "reference" if (journey.get("campaign") or {}).get("route") == "reference" or (
                journey.get("reference") and not journey.get("labStock")) else "stock"
        campaign = journey.get("campaign") or {}
        scope = (route + "/" + campaign["guideCampaign"]
                 if route == "reference" and campaign.get("guideCampaign") else route)
        return "/".join((channel, "Original", route, scope))

    def _saved_guide_story(self):
        """Resolve only the selected Continue or the ports attached to this owned session."""
        record = self.record
        if not record or not record["verified"]:
            return {}
        channel, profile, backend, route = self._guide_branch().split("/", 3)
        if channel not in ("lab", "play") or profile != "Original" or backend not in ("stock", "reference"):
            return {}
        if route != backend and not (backend == "reference" and re.fullmatch(
                r"restored/[0-9a-f]{32}|reference/\d{8}T\d{12}Z", route)):
            return {}
        try:
            if self.process is not None:
                operation = self.played_cards or {}
                lock = operation.get("lock", {})
                if (operation.get("game") != self.game or lock.get("content") != record["fingerprint"]
                        or lock.get("profile") != profile):
                    return {}
                paths = operation.get("paths", {})
            else:
                journey = self.journeys.get(self.game, {})
                campaign = (journey.get("stockCampaign") if backend == "stock" and channel == self.channel
                            else journey.get("campaign"))
                if not campaign or campaign.get("route") != backend:
                    return {}
                if backend == "stock":
                    paths = managed_cards.duckstation_paths(self.root, channel, self.game, Path(record["cue"]))
                else:
                    selected = campaign.get("id", "")
                    if not re.fullmatch(r"\d{8}T\d{12}Z", selected):
                        return {}
                    folder = plain_path(self.root / "lab/reference-play" / self.game / selected)
                    status = runtime_reference_play.reference_status(self.root, self.game)
                    if not status["ready"]:
                        return {}
                    receipt = read_object(folder / "session.json")
                    if runtime_reference_play.reading_campaign(receipt, selected) != campaign.get("guideCampaign", ""):
                        return {}
                    paths = self._closed_reference_paths(
                        folder, receipt, self.game, status, runtime_setup._digest(Path(record["cue"])),
                        runtime_setup._catalogue()["openbios-psx-rom"]["member"]["sha256"], None,
                    )
            channel_root = plain_path(self.root / channel)
            if not all(plain_path(path).is_relative_to(channel_root) for path in paths.values()):
                return {}
            if (self.game == "bof4" and backend == "reference" and channel == "lab" and paths
                    and record.get("fingerprint") == guide_story.REVISIONS["bof4"]
                    and record.get("serial") == managed_cards.SERIALS["bof4"]):
                if self.process is not None:
                    recorder = operation.get("visits")
                    if recorder:
                        if recorder.detached:
                            return {}
                        current = guide_visits.live_context(recorder.folder, recorder.token)
                        if current is not None:
                            return current
                else:
                    witnessed = guide_visits.saved_context(folder, paths)
                    if witnessed:
                        return witnessed
            return guide_story.saved_story(self.game, record, paths)
        except (OSError, ValueError, RuntimeError):
            return {}

    def _shortcut_model(self):
        keys = self._shortcut_keys()
        choices = self._shortcut_pads()
        mapping = None
        if (self.pad.handle and not self.pad.raw and len(self.pad.devices) == 1
                and self.settings.get("setup_gameplay", True) is not False):
            mapping = resolve_gameplay(self.settings["gameplay_bindings"].get(self.pad.profile, {}))
        free = [button for button in HOST_BUTTONS if mapping is not None and button not in mapping.values()
                and button not in (PAUSE_BUTTON, "left trigger", "right trigger")]
        branch = self._guide_branch().split("/")
        managed_playback, reference = branch[0] == "lab", branch[2] == "reference"
        guide = (self.played_cards or {}).get("guide") or self._guide_binding(
            mapping if managed_playback else None, reference=reference,
            checkpoints_enabled=managed_playback and self.game == "bof3" and not reference,
        )
        if guide["pad"] in free:
            free.remove(guide["pad"])
        if reference:
            free = []
        bindings = shortcut_bindings(keys, choices, None if reference else mapping, self.settings.get("bof3_hold_2x") is True,
                                     reserved=(guide["pad"],))
        reverse = {value[1]: button for button, value in HOST_BUTTONS.items()}
        return {"guide": guide} | {
            action: {"key": key, "pad": reverse[bindings[action][1].split("/")[-1]]
                     if len(bindings[action]) > 1 else "",
                     "padChoice": choices.get(action, "none" if action == "suspend" else "auto"),
                     "keys": [option for option in self._available_shortcut_keys(action)
                              if option not in keys.values() or option == key],
                     "buttons": free}
            for action, key in keys.items()
        }

    def snapshot(self):
        record = self.record
        rules = self.rulebooks.get(
            (self.root, self.game, (record or {}).get("fingerprint"))
        )
        ready = bool(record and record["verified"] and self.runtime["can_launch"])
        reference_ready = bool(
            self.channel == "lab" and record and record["verified"]
            and not ready and runtime_reference_play.reference_status(self.root, self.game)["ready"]
        )
        primary = (
            "Add game archive"
            if not record
            else ("Play in Lab" if self.channel == "lab" else "Play game")
            if ready
            else "Play in Redux Lab"
            if reference_ready
            else "Open Workshop"
            if self.runtime.get("compatibility_blocked")
            else "Finish setup"
        )
        points = [
            {
                "id": p["id"],
                "title": p["created_utc"][:16].replace("T", " "),
                "campaign": p["campaign"],
                "checkpointCopy": str(p.get("route", "")).startswith("checkpoint/"),
                "saveTitle": p.get("save_title", ""),
                "channel": p["channel"],
                "cards": sum(f["kind"] == "card" for f in p["files"]),
                "states": sum(f["kind"] == "state" for f in p["files"]),
            }
            for p in self.history[:100]
        ]
        mapping = {**DEFAULT, **self.settings["bindings"].get(self.pad.profile, {})}
        prompts = (
            (
                self.pad.glyph(mapping["select"])
                + " Select    "
                + self.pad.glyph(mapping["back"])
                + " Back"
            )
            if self.pad.handle
            else "Enter  Select    Esc  Back"
        )
        return {
            "version": self.version,
            "game": self.game,
            "title": TITLES[self.game],
            "channel": self.channel,
            "page": self.page,
            "guideAvailable": sys.platform == "win32",
            "guideReading": self.guide_session.reading,
            "guideRequest": self.guide_request,
            "guideEntry": self.guide_entry,
            "guideStory": self.guide_story,
            "campaignStory": self.campaign_story,
            "guideBranch": self._guide_branch(),
            "guideStatus": ("Game can continue while you read. Use F6 in the game to pause."
                            if self.played_cards and self.played_cards.get("backend") == "reference" else ""),
            "guideError": self.guide_error,
            "tv": bool(self.settings.get("tv", False)),
            "primary": primary,
            "homeHeading": (
                "Game running"
                if self.process
                else "Add your game"
                if not record
                else "Research Lab"
                if reference_ready
                else "Playback on hold"
                if self.runtime.get("compatibility_blocked")
                else "Set up the runtime"
                if not self.runtime["runtime_ready"]
                else "Choose a PlayStation BIOS"
                if not self.runtime["firmware_ready"]
                else "Research Lab"
                if self.channel == "lab"
                else "Ready to play"
            ),
            "library": str(self.root),
            "games": self.records,
            "record": record,
            "points": points,
            "restored": self.restored,
            "runtime": {
                k: self.runtime.get(k)
                for k in (
                    "version",
                    "runtime_ready",
                    "firmware_ready",
                    "firmware",
                    "reason",
                    "running",
                    "compatibility_blocked",
                )
            },
            "canLaunch": ready,
            "journeys": self.journeys,
            "art": self.art,
            "preferences": {
                "menuMusic": self.settings.get("menu_music") is True,
                "menuVolume": self._menu_volume(),
                "reduceMotion": self.settings.get("reduce_motion") is True,
                "presentation": self.settings.get("bof3_presentation") or "original",
                "fastForward": self.settings.get("bof3_hold_2x") is True,
                "leftStick": bool(self.pad.handle) and not self.pad.raw
                    and len(self.pad.devices) == 1
                    and self.settings.get("setup_gameplay", True) is not False
                    and "left stick" not in self.settings["gameplay_bindings"].get(self.pad.profile, {}).values(),
            },
            "shortcuts": self._shortcut_model(),
            "checkpoints": [
                kind for kind in checkpoints.KINDS
                if self.channel == "lab" and sys.platform == "win32" and
                checkpoints.path_for(self.root, self.game, kind).is_file()
            ],
            "resumeAvailable": self.suspend_ready,
            "checkpointControls": self.channel == "lab" and sys.platform == "win32"
                and (self.journeys.get(self.game, {}).get("labStock") if self.game == "bof3"
                     else self.journeys.get(self.game, {}).get("reference")),
            "outcome": self.outcome,
            "referenceReady": reference_ready,
            "integerReady": ready and self.channel == "lab" and self.game == "bof3",
            "job": dict(self.job),
            "message": self.message,
            "playing": self.process is not None,
            "discovered": [
                {
                    "name": r["name"]
                    + (" · " + r["member"] if r.get("member") else ""),
                    "id": str(i),
                }
                for i, r in enumerate(self.discovered)
            ],
            "firmwareChoices": [
                {"member": r["member"], "name": r["name"], "region": r["region"]}
                for r in self.firmware_members
            ],
            "workshop": {
                "rules": rules.model() if rules else None,
                "counts": self.workshop.get("summary", {}),
                "previews": [
                    p.get("label", "Preview") for p in self.workshop.get("previews", [])
                ],
            },
            "input": {
                "name": self.pad.name,
                "family": self.pad.family,
                "connected": bool(self.pad.handle),
                "count": len(self.pad.devices),
                "status": self.pad.error,
                "last": self.pad.last_input,
                "raw": self.pad.raw,
                "bindings": mapping,
                "gameplay": resolve_gameplay(self.settings["gameplay_bindings"].get(self.pad.profile, {})),
                "gameplayEnabled": self.settings.get("setup_gameplay", True) is not False,
                "gameplayDevice": bool(self.pad.handle and not self.pad.raw and len(self.pad.devices) == 1),
                "prompts": prompts,
                "capture": self.capture_action,
                "proposal": self.proposed_binding,
            },
        }

    def _start(self, phase, callback: Callable, cancellable=False, *, starting_game=False):
        if self.worker is not None or self.process is not None:
            raise ValueError("Finish the current operation first.")
        self.cancel.clear()
        self.outcome = {}
        self.job = {"phase": phase, "done": 0, "total": 0, "cancellable": cancellable}
        self.message = ""
        self.starting_game = starting_game

        def run():
            try:
                result = callback()
                self.events.put(("complete", result))
            except Exception as exc:
                self.events.put(("failure", str(exc) or type(exc).__name__))

        self.worker = threading.Thread(
            target=run, name="Atelier local operation", daemon=False
        )
        self.worker.start()

    def _import_files(self, names):
        if not isinstance(names, list) or not 0 < len(names) <= 16:
            raise ValueError("Select one to sixteen game archives or CUE files.")
        root = self.root

        def run():
            outcomes = []
            selected = None
            for name in names:
                path = Path(name)
                if self.cancel.is_set():
                    outcomes.append("Import cancelled.")
                    break

                def progress(phase, done, total):
                    self.events.put(
                        (
                            "progress",
                            {
                                "phase": str(phase).capitalize() + " · " + path.name,
                                "done": done,
                                "total": total,
                                "cancellable": True,
                            },
                        )
                    )

                try:
                    result = import_games.import_game(
                        path, root / "games", cancel=self.cancel, progress=progress
                    )
                    if result["game"] in TITLES:
                        selected = result["game"]
                    outcomes.append(
                        f"{path.name}: {result['outcome'].replace('_', ' ')}."
                    )
                except (OSError, ValueError) as error:
                    outcomes.append(f"{path.name}: {error}")
            return {"message": "\n".join(outcomes), "game": selected,
                    "imported": selected is not None}

        self._start("Reading archives", run, True)

    def _prepare(self):
        runtime_setup.prepare_runtime(self.root, self.channel)
        return {"message": "The pinned runtime is ready."}

    def _launch(self, mode="stock", *, scoped_lab=False, continue_lab=False, backup=None, restored=None,
                checkpoint_kind=None):
        record = self.record
        if not record or not record["verified"]:
            raise ValueError("Import this game revision first.")
        if mode != "stock" and self.channel != "lab" and not scoped_lab:
            raise ValueError("Select Research Lab to try this runtime.")
        if mode == "stock" and self.runtime.get("compatibility_blocked"):
            raise ValueError(self.runtime["reason"])
        game, channel = self.game, self.channel
        if scoped_lab:
            channel = "lab"
        campaign = self.journeys.get(game, {}).get("campaign")
        if continue_lab and (not campaign or campaign.get("route") != "reference"):
            raise ValueError("A verified closed Lab campaign could not be found.")
        edition_lock = self._edition()
        checkpoint_enabled = (channel == "lab" and sys.platform == "win32" and not backup and not restored
                              and (game, mode) in {("bof3", "stock"), ("bof4", "reference")})
        keys = self._shortcut_keys()

        def checkpoint_for(ordinary_paths):
            if not checkpoint_enabled:
                return None
            integrity = checkpoint_session.identity(self.root, game, record, mode, operation["lock"])
            operation["checkpoint"] = {"identity": integrity, "anchor": None}
            if checkpoint_kind is None:
                return None
            try:
                ordinary = managed_cards.read_cards(game, ordinary_paths)
                anchor = checkpoints.card_identity(ordinary.slots) if ordinary.title else {}
                selected = checkpoints.load(self.root, game, checkpoint_kind, integrity, anchor)
            except (OSError, ValueError, RuntimeError):
                operation["notice"] = "Checkpoint unavailable. Choose Load Game to continue from your ordinary save."
                return None
            operation["checkpoint"]["anchor"] = anchor
            return selected

        gameplay = None
        if (channel == "lab" and sys.platform == "win32"
                and self.settings.get("setup_gameplay", True) is not False
                and (not self.pad.devices or (len(self.pad.devices) == 1 and self.pad.handle and not self.pad.raw))):
            gameplay = resolve_gameplay(self.settings["gameplay_bindings"].get(self.pad.profile, {}))
        guide = self._guide_binding(gameplay if mode in ("stock", "reference") else None,
                                    for_launch=True, reference=mode == "reference",
                                    checkpoints_enabled=checkpoint_enabled)
        guide["profile"] = self.pad.profile if self.pad.handle else ""

        def start_runtime():
            cue = Path(record["cue"])
            if mode == "reference":
                reference_status = runtime_reference_play.reference_status(self.root, game)
                if not reference_status["ready"]:
                    raise ValueError(reference_status["reason"])
                operation["lock"] = edition_lock | {
                    "runtime": reference_status["version"], "backend": reference_status["backend"],
                    "firmware": runtime_setup._catalogue()["openbios-psx-rom"]["member"]["sha256"],
                }
                branch = restored
                card_seed = None
                previous = campaign["id"] if continue_lab else None
                ordinary_paths = managed_cards.slot_paths(
                    self.root / "lab/reference-play" / game / previous
                ) if previous else {}
                selected = checkpoint_for(ordinary_paths)
                if selected is not None:
                    branch = uuid4().hex
                    operation["route"] = "checkpoint/" + branch
                    previous = None
                if backup or branch:
                    if backup:
                        receipt = campaigns.CampaignStore(self.root).restore_to_lab(
                            backup, edition_lock, cards_only=True
                        )
                        branch = receipt["id"]
                    elif selected is None:
                        receipt = read_object(self.root / "lab/restored" / game / branch / "branch.json")
                    if selected is None:
                        folder = self.root / "lab/restored" / game / branch
                        previous_copy = self._reference_campaign(game, record, reference_status, branch)
                        previous = previous_copy["id"] if previous_copy else None
                        if not previous:
                            validated = managed_cards.restored_cards(folder, receipt)
                            if not validated.title:
                                raise ValueError("This backup has no verified in-game save for the selected title.")
                            card_seed = validated.slots
                        operation["route"] = "restored/" + branch
                        operation["parent"] = receipt["parent"]
                return runtime_reference_play.launch_reference_game(
                    self.root, game, cue, from_session=previous, restored_branch=branch, card_seed=card_seed,
                    **({"checkpoint_keys": keys, "checkpoint": selected} if checkpoint_enabled else {}),
                    **({"gameplay": gameplay} if gameplay is not None else {})
                )
            if mode == "integer":
                return edition_session.launch_integer_lab(self.root, game, cue)
            status = runtime_setup.game_launch_status(self.root, game, channel)
            operation["lock"] = edition_lock | {"runtime": status["version"],
                                                  "firmware": status.get("firmware_sha256", ""),
                                                  "backend": "duckstation"}
            operation["paths"] = managed_cards.duckstation_paths(self.root, channel, game, cue)
            preferences = {}
            if (game, channel) == ("bof3", "lab"):
                presentation = self.settings.get("bof3_presentation")
                if presentation in ("original", "crisp"):
                    preferences["presentation"] = presentation
                fast_forward = self.settings.get("bof3_hold_2x")
                if type(fast_forward) is bool:
                    preferences["fast_forward"] = fast_forward
            selected = checkpoint_for(operation["paths"])
            if checkpoint_enabled:
                controls = shortcut_bindings(keys, self._shortcut_pads(), gameplay,
                                             preferences.get("fast_forward") is True, reserved=(guide["pad"],))
                if selected is not None:
                    process = checkpoint_session.launch_stock_copy(
                        self.root, game, cue, selected, controls, gameplay, preferences
                    )
                    operation["paths"] = process.atelier_cards
                    operation["route"] = "checkpoint/" + uuid4().hex
                    return process
                preferences["checkpoint_controls"] = controls
            return runtime_setup.launch_game(
                self.root, game, cue, channel, **preferences,
                **({"gameplay": gameplay} if gameplay is not None else {})
            )

        operation = {"game": game, "channel": channel, "lock": edition_lock, "route": mode,
                     "backend": mode, "guide": guide,
                     "parent": None, "paths": {}}

        def open_game():
            process = session.launch(self.root, start_runtime)
            if mode == "reference":
                operation["paths"] = process.atelier_cards
                operation["guideCampaign"] = process.atelier_guide_campaign
                if game == "bof4":
                    operation["visits"] = getattr(process, "atelier_visit_recorder", None)
            if checkpoint_enabled:
                operation["checkpoint"]["files"] = getattr(process, "atelier_checkpoints", {})
            return {
                "message": operation.get("notice", "Game running. Use the runtime menu to pause or exit."),
                "process": process, "played_cards": operation,
            }

        self.guide_session.arm_launch(self.player_hwnd)
        try:
            self._start("Checking game and runtime", open_game, starting_game=True)
        except Exception:
            self.guide_session.cancel_launch()
            raise

    def _apply_binding(self):
        if not self.proposed_binding or time.monotonic() >= self.binding_deadline:
            raise ValueError("The proposed mapping expired. Select the action again.")
        action, key = self.proposed_binding
        gameplay = action.startswith("game:")
        store = self.settings["gameplay_bindings" if gameplay else "bindings"]
        defaults = GAMEPLAY_DEFAULTS if gameplay else DEFAULT
        action = action.removeprefix("game:") if gameplay else action
        if gameplay and (key not in HOST_BUTTONS or key == PAUSE_BUTTON):
            raise ValueError("Choose a gameplay button. The right stick click is reserved for the DuckStation pause menu.")
        mapping = {**defaults, **store.get(self.pad.profile, {})}
        previous = mapping[action]
        for other, button in mapping.items():
            if other != action and button == key:
                mapping[other] = previous
        mapping[action] = key
        store[self.pad.profile] = mapping
        self._save()
        self.capture_action, self.proposed_binding = "", None
        self.pad.edges.reset()

    def _menu_volume(self):
        value = self.settings.get("menu_volume", 25)
        return value if type(value) is int and 0 <= value <= 100 else 25

    def action(self, name, value=None):
        if name == "poll":
            return self.poll()
        if name == "snapshot":
            return self.snapshot()
        if self.process is not None and name not in {"focus", "openGuide", "returnToGame"}:
            raise ValueError("Return to the game and close it before changing the campaign or its settings.")
        if name == "openGuide":
            self.guide_error = ""
            if self.starting_game or self.worker:
                raise ValueError("Wait for the current operation to finish.")
            if self.process is not None and not self.guide_session.reading:
                self.guide_session.open(self.process, self.player_hwnd)
            self.page = "Field guide"
            self.guide_entry = value if isinstance(value, str) else "guide"
            self.guide_story = self._saved_guide_story()
            self.guide_request += 1
            self.pad.edges.reset()
            self.version += 1
            return
        if name == "returnToGame":
            self.guide_error = ""
            if self.process is None or not self.guide_session.reading:
                raise ValueError("This game session has closed.")
            if self.guide_session.return_to_game(self.process, self.player_hwnd):
                self.page = "Journey"
                self.guide_story = {}
                self.pad.edges.reset()
                self.version += 1
            return
        if name == "assetPreview":
            previews = self.workshop.get("previews", [])
            if type(value) is not int or not 0 <= value < len(previews):
                raise ValueError("Choose an available local preview.")
            meta = previews[value]
            path = plain_path(Path(self.workshop["folder"]) / member_path(meta["file"]))
            if (
                path.suffix.lower() != ".png"
                or not 0 < path.stat().st_size < 4 * 1024**2
            ):
                raise ValueError("Unsupported preview file.")
            data = path.read_bytes()
            if (
                not data.startswith(b"\x89PNG\r\n\x1a\n")
                or hashlib.sha256(data).hexdigest() != meta["sha256"]
            ):
                raise ValueError("The local preview failed verification.")
            return {
                "url": "data:image/png;base64,"
                + base64.b64encode(data).decode("ascii"),
                "description": meta.get("interpretation", ""),
            }
        if name == "focus":
            self.focus = bool(value)
            self.pad.edges.reset()
            return None
        if name == "cancel":
            if self.job.get("cancellable"):
                self.cancel.set()
            return None
        if name in (
            "page",
            "captureBinding",
            "acceptBinding",
            "discardBinding",
            "nextDevice",
            "resetBindings",
            "resetGameplay",
            "toggleGameplay",
            "menuMusic",
            "menuVolume",
            "reduceMotion",
            "tv",
            "refresh",
        ):
            if name == "page":
                if value not in PAGES:
                    raise ValueError("Unknown Player view.")
                self.page = value
                self.guide_story = self._saved_guide_story() if value == "Field guide" else {}
                self.outcome = {}
            elif name == "captureBinding":
                game_action = isinstance(value, str) and value.startswith("game:")
                valid_gameplay = game_action and value[5:] in GAMEPLAY_DEFAULTS and not self.pad.raw and len(self.pad.devices) == 1
                if not self.pad.handle or not isinstance(value, str) or (not valid_gameplay and value not in DEFAULT):
                    raise ValueError("Connect a controller and choose an action first.")
                self.capture_action = value
                self.proposed_binding = None
                self.pad.edges.reset()
            elif name == "discardBinding":
                self.capture_action = ""
                self.proposed_binding = None
            elif name == "acceptBinding":
                self._apply_binding()
            elif name == "nextDevice":
                self.pad.next_device()
                self.capture_action = ""
                self.proposed_binding = None
            elif name == "resetBindings":
                self.settings["bindings"].pop(self.pad.profile, None)
                self.capture_action = ""
                self.proposed_binding = None
                self._save()
            elif name == "resetGameplay":
                self.settings["gameplay_bindings"].pop(self.pad.profile, None)
                self.capture_action = ""
                self.proposed_binding = None
                self._save()
            elif name == "toggleGameplay":
                self.settings["setup_gameplay"] = self.settings.get("setup_gameplay", True) is False
                self._save()
            elif name == "tv":
                self.settings["tv"] = not self.settings.get("tv", False)
                self._save()
            elif name in ("menuMusic", "reduceMotion") and type(value) is bool:
                self.settings["menu_music" if name == "menuMusic" else "reduce_motion"] = value
                self._save()
            elif name == "menuVolume" and type(value) is int and 0 <= value <= 100:
                self.settings["menu_volume"] = value
                self._save()
            elif name == "refresh":
                self.refresh()
        else:
            if self.worker is not None or self.process is not None:
                raise ValueError("Finish the current operation first.")
            if name == "selectGame" and value in TITLES:
                self.game = value
                self.outcome = {}
                self._save()
                self.refresh()
            elif name == "channel" and value in ("play", "lab"):
                self.channel = value
                self.firmware_source, self.firmware_members = None, []
                self._save()
                self.refresh()
            elif name == "library":
                location = plain_path(Path(value))
                if not location.is_dir():
                    raise ValueError("Choose an existing library folder.")
                self.root = location
                self.message = ""
                self.discovered = []
                self.firmware_source, self.firmware_members = None, []
                self._load_preferences()
                self.refresh()
                if self.remember_library:
                    atomic_bytes(
                        self.selection_file, canonical_bytes({"path": str(location)})
                    )
            elif name == "import":
                self._import_files(value)
            elif name == "prepare":
                self._start("Verifying local runtime package", self._prepare)
            elif name == "existingRuntime":

                def reuse():
                    from tools.existing_runtime import reuse_installation

                    reuse_installation(self.root, Path(value), self.channel)
                    return {
                        "message": "The verified runtime files are ready in this channel."
                    }

                self._start("Checking the selected installation", reuse)
            elif name in ("runtimePackage", "reduxPackage", "labPackage"):
                backend = "duckstation" if name == "runtimePackage" else "pcsx-redux"
                package_channel = "lab" if name == "labPackage" else self.channel
                if backend == "pcsx-redux" and package_channel != "lab":
                    raise ValueError("Select Research Lab for replacement firmware.")

                def install():
                    source = Path(value)
                    if backend == "pcsx-redux" and sys.platform.startswith("linux"):
                        runtime_linux.prepare(self.root, source)
                    else:
                        selected = backend
                        if backend == "pcsx-redux" and source.stat().st_size == runtime_setup._component(
                                runtime_reference_play.BACKEND, "lab")["package"]["bytes"]:
                            selected = runtime_reference_play.BACKEND
                        if name == "labPackage" and selected != runtime_reference_play.BACKEND:
                            raise ValueError("Choose the reviewed PCSX-Redux Windows console ZIP.")
                        runtime_setup.import_runtime_package(self.root, source, package_channel, selected)
                    return {
                        "message": "Official package verified and prepared for this channel."
                    }

                self._start("Verifying selected package", install)
            elif name == "repair":

                def repair():
                    runtime_setup.repair_runtime(self.root, self.channel)
                    return {
                        "message": "Runtime repair complete. Review its readiness below."
                    }

                self._start("Repairing pinned runtime", repair)
            elif name == "labFirmware":
                if self.channel != "lab":
                    raise ValueError("Select Research Lab first.")

                def replacement():
                    runtime_setup.use_lab_openbios(self.root)
                    return {
                        "message": "The verified replacement firmware is configured in Lab."
                    }

                self._start("Checking the official Lab firmware", replacement)
            elif name == "firmware":
                self.firmware_source, self.firmware_members = None, []

                def bind():
                    path = Path(value["path"] if isinstance(value, dict) else value)
                    if isinstance(value, dict):
                        member = value.get("member")
                    else:
                        choices = firmware.firmware_choices(path)
                        if len(choices) > 1:
                            return {
                                "firmwareSource": path,
                                "firmwareChoices": choices,
                                "message": "Choose which identified firmware file to use.",
                            }
                        member = choices[0]["member"]
                    runtime_setup.import_firmware(self.root, path, self.channel, member)
                    return {
                        "message": "Firmware identified and configured for this channel."
                    }

                self._start("Identifying firmware", bind)
            elif name == "firmwareMember":
                if not self.firmware_source or not any(
                    r["member"] == value for r in self.firmware_members
                ):
                    raise ValueError(
                        "Choose a firmware file from the identified archive."
                    )
                return self.action(
                    "firmware", {"path": str(self.firmware_source), "member": value}
                )
            elif name == "discover":

                def find():
                    found = firmware.discover_firmware(Path(value))
                    return {
                        "discovered": found,
                        "message": f"{len(found)} compatible firmware file(s) in the selected folder.",
                    }

                self._start("Checking selected folder", find)
            elif name == "bindDiscovered":
                match = next(
                    (r for i, r in enumerate(self.discovered) if str(i) == value), None
                )
                if not match:
                    raise ValueError("Choose an identified file first.")
                return self.action(
                    "firmware", {"path": match["path"], "member": match.get("member")}
                )
            elif name == "launch":
                self._launch()
            elif name == "openLab" and value in ("reference", "continue", "stock"):
                self._launch("reference" if value != "stock" else "stock",
                             scoped_lab=True, continue_lab=value == "continue")
            elif name == "presentation" and value in ("original", "crisp"):
                self.settings["bof3_presentation"] = value
                self._save()
            elif name == "hold2x" and type(value) is bool:
                self.settings["bof3_hold_2x"] = value
                self._save()
            elif name in ("shortcutKey", "shortcutPad") and isinstance(value, dict):
                shortcut, choice = value.get("action"), value.get("choice")
                if not isinstance(shortcut, str) or shortcut not in (*SHORTCUT_KEYS, "guide") or not isinstance(choice, str):
                    raise ValueError("Choose an available shortcut.")
                model = self._shortcut_model()[shortcut]
                if shortcut == "guide":
                    profiles = self.settings.get("guide_shortcuts")
                    profiles = dict(profiles) if isinstance(profiles, dict) else {}
                    profile = profiles.get(self.game)
                    profile = dict(profile) if isinstance(profile, dict) else {}
                    if name == "shortcutKey" and choice in model["keys"]:
                        profile["key"] = choice
                    elif name == "shortcutPad" and choice in {"auto", "none", *model["buttons"]}:
                        pads = profile.get("pads")
                        profile["pads"] = (pads if isinstance(pads, dict) else {}) | {self.pad.profile: choice}
                    else:
                        raise ValueError("Choose a free Field guide shortcut.")
                    self.settings["guide_shortcuts"] = profiles | {self.game: profile}
                elif name == "shortcutKey" and choice in model["keys"]:
                    profiles = self.settings.get("shortcut_keys")
                    self.settings["shortcut_keys"] = (profiles if isinstance(profiles, dict) else {}) | {
                        self.game: self._shortcut_keys() | {shortcut: choice}
                    }
                elif name == "shortcutPad" and choice in {"auto", "none", *model["buttons"]}:
                    profiles = self.settings.get("shortcut_pads")
                    self.settings["shortcut_pads"] = (profiles if isinstance(profiles, dict) else {}) | {
                        self.pad.profile: self._shortcut_pads() | {shortcut: choice}
                    }
                else:
                    raise ValueError("That input is already in use or unavailable.")
                self._save()
                self.version += 1
            elif name == "resumeCheckpoint" and self.channel == "lab" and sys.platform == "win32":
                if value not in checkpoints.KINDS:
                    raise ValueError("Choose Quick save or Suspend.")
                reference = self.game == "bof4"
                route = self.journeys.get(self.game, {}).get("campaign")
                self._launch("reference" if reference else "stock",
                             continue_lab=reference and bool(route and route["route"] == "reference"),
                             checkpoint_kind=value)
            elif name in ("playBackup", "playRestored"):
                if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
                    raise ValueError("Select an available Lab save.")
                rows = self.history if name == "playBackup" else self.restored
                if not any(row["id"] == value for row in rows):
                    raise ValueError("Select a save for this game.")
                self._launch("reference", scoped_lab=True,
                             **({"backup": value} if name == "playBackup" else {"restored": value}))
            elif name in ("launchReference", "launchInteger"):
                self._launch("reference" if name == "launchReference" else "integer")
            elif name in ("openRules", "ruleControl"):
                if not self.record or not self.record["verified"]:
                    raise ValueError(
                        "Import the verified revision to inspect its rules."
                    )
                identity = (self.root, self.game, self.record["fingerprint"])
                if name == "openRules":

                    def open_rules():
                        return {
                            "rules": (
                                identity,
                                Rulebook(
                                    progression.game_tables(
                                        self.root / "games" / self.game
                                    )
                                ),
                            ),
                            "message": "Original rules ready.",
                        }

                    self._start("Reading the original rules", open_rules)
                elif identity in self.rulebooks:
                    self.rulebooks[identity].apply(value)
                else:
                    raise ValueError("Open the original rules first.")
            elif name == "catalogue":
                if not self.record:
                    raise ValueError("Add the selected game first.")

                def catalogue():
                    def progress(phase, done, total):
                        self.events.put(
                            (
                                "progress",
                                {
                                    "phase": phase,
                                    "done": done,
                                    "total": total,
                                    "cancellable": True,
                                },
                            )
                        )

                    result = workshop_assets.catalogue_game(
                        self.root / "games" / self.game,
                        cancel=self.cancel,
                        progress=progress,
                    )
                    return {
                        "message": f"Asset catalogue ready: {result['preview_count']} private previews."
                    }

                self._start("Reading local disc catalogue", catalogue, True)
            elif name == "restoreCards":
                if not any(
                    p["id"] == value and any(f["kind"] == "card" for f in p["files"])
                    for p in self.history
                ):
                    raise ValueError("Select an ordinary card restore point.")

                def restore():
                    result = campaigns.CampaignStore(self.root).restore_to_lab(
                        value, self._edition(), cards_only=True
                    )
                    return {
                        "message": "Card restored into a separate Lab branch: "
                        + result["path"]
                    }

                self._start("Restoring memory cards to Lab", restore)
            elif name == "capture":
                if self.runtime.get("running"):
                    raise ValueError("Close the runtime before taking a snapshot.")

                def backup():
                    result = campaigns.CampaignStore(self.root).capture(
                        self.game, Path(value), self._edition(), closed=True, channel=self.channel,
                    )
                    return {"message": f"Captured {len(result['files'])} save file(s)."}

                self._start("Verifying closed save files", backup)
            else:
                raise ValueError("This Player action is unavailable.")
        self.version += 1
        return self.snapshot()

    def poll(self):
        while True:
            try:
                kind, item = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self.job = item
                self.version += 1
                continue
            self.job = {}
            self.worker = None
            self.starting_game = False
            if kind == "failure":
                self.message = item
                self.outcome = {"error": True}
                self.guide_session.cancel_launch()
            else:
                self.message = item.get("message", "")
                self.outcome = {"error": False, "imported": item.get("imported", False)}
                if item.get("game") in TITLES:
                    self.game = item["game"]
                    self._save()
                if "discovered" in item:
                    self.discovered = item["discovered"]
                if "rules" in item:
                    identity, rules = item["rules"]
                    self.rulebooks[identity] = rules
                if "firmwareChoices" in item:
                    self.firmware_source = item["firmwareSource"]
                    self.firmware_members = item["firmwareChoices"]
                if "process" in item:
                    self.process = item["process"]
                    self.played_cards = item.get("played_cards")
                    self.pad.edges.reset()
                    self.released_to_runtime = True
            self.refresh()
        if self.player_hwnd and (self.starting_game or self.process is not None):
            self.guide_session.poll_launch(self.process, self.player_hwnd)
        returned = False
        visits = (self.played_cards or {}).get("visits")
        if visits and time.monotonic() >= self.next_visit_sample:
            self.next_visit_sample = time.monotonic() + 0.2
            visits.sample()
        if self.process is not None and (code := self.process.poll()) is not None:
            if visits:
                # Some runtimes finish writing the memory card during shutdown.
                visits.sample()
            if self.guide_session.reading:
                self.page = "Journey"
            self.guide_session.reset()
            self.guide_error = ""
            self.process = None
            self.pad.edges.reset()
            returned = True
            self.message = (
                "Game closed."
                if code == 0
                else f"The runtime closed with error {code}. Check Library & setup."
            )
            self.outcome = {"error": code != 0, "returned": True}
            operation, self.played_cards = self.played_cards, None
            if code == 0 and operation and operation["paths"]:
                try:
                    point = session.backup(self.root, operation)
                    if point:
                        self.message = "In-game save backed up."
                        if visits:
                            try:
                                guide_visits.preserve_restore_point(self.root, point, visits)
                            except (OSError, ValueError, KeyError):
                                self.message = "In-game save backed up. Choose a guide page when restoring it."
                except (OSError, ValueError, RuntimeError, sqlite3.DatabaseError) as error:
                    self.message = f"Game closed. Automatic backup needs attention. {error}"
            if code == 0 and operation and operation.get("checkpoint"):
                try:
                    with session.idle(self.root):
                        kinds = checkpoint_session.capture(self.root, operation)
                    if kinds:
                        self.message = "Suspended. Resume from Saves." if "suspend" in kinds else "Quick save ready in Saves."
                except (OSError, ValueError, RuntimeError) as error:
                    self.message = f"Checkpoint could not be saved. {error}"
            if code != 0 and operation and operation["route"].startswith("checkpoint/"):
                self.message = "The checkpoint could not open. Use Continue to load your ordinary save."
            self.refresh()
        before = (
            self.pad.name,
            self.pad.device_id,
            len(self.pad.devices),
            self.pad.last_input,
        )
        move, physical = self.pad.poll(
            self.settings["bindings"],
            self.focus and not self.starting_game and (
                self.guide_session.reading and self.guide_session.player_foreground(self.player_hwnd)
                or self.process is None and not self.released_to_runtime
            ),
        )
        if self.process is not None and self.player_hwnd and self.played_cards:
            operation = self.played_cards
            guide = operation.get("guide")
            if guide:
                request = self.guide_session.poll(self.process, self.player_hwnd, self.pad, guide)
                if request:
                    self.action("openGuide" if request == "open" else "returnToGame")
                    move = None
        if self.process is None:
            self.released_to_runtime = False
        if before[1] != self.pad.device_id:
            self.capture_action = ""
            self.proposed_binding = None
        if before != (
            self.pad.name,
            self.pad.device_id,
            len(self.pad.devices),
            self.pad.last_input,
        ):
            self.version += 1
        if self.proposed_binding and time.monotonic() >= self.binding_deadline:
            self.proposed_binding = None
            self.message = "Mapping preview expired. The previous binding is active."
            self.version += 1
        if self.capture_action:
            if physical and self.capture_action.startswith("game:") and (physical not in HOST_BUTTONS or physical == PAUSE_BUTTON):
                self.message = "Choose a gameplay button. The right stick click is reserved for the DuckStation pause menu."
                self.version += 1
                physical = None
            if physical:
                self.proposed_binding = [self.capture_action, physical]
                self.binding_deadline = time.monotonic() + 15
                self.capture_action = ""
                self.pad.edges.reset()
                self.version += 1
            move = None
        return {"version": self.version, "move": move, "returned": returned}

    def close(self):
        self.cancel.set()
        if self.worker is not None:
            self.worker.join()
        self.pad.close()
