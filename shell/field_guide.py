"""Offline Field Guide resources, exact-disc lookups and branch-local reading marks."""
from __future__ import annotations

import base64
import binascii
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable
from xml.etree import ElementTree

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, Property, Qt, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from tools import progression
from tools.guide_floors import read_floors
from tools.workshop_assets import open_imported_disc
from tools.guide_capture_refs import PLATES
from tools.local_store import plain_path
from shell.guide_book import CORE_PAGES, EARLY_PLACES, GENE_PLATES, public_gene_recipe, read_book


PLATE_PATTERN = re.compile(r"--art-([a-z][a-z0-9-]*):\s*url\('((?:data:image/webp;base64,)[A-Za-z0-9+/=]+)'\)")


class ReadingMarks:
    """Small, independently transactional records, with no access to cards or states."""

    def __init__(self, root: Path, game: str, revision: str, branch: str, book: dict | None = None):
        channel = branch.partition("/")[0]
        self.db = root / (channel if channel in ("lab", "play") else "atelier") / "field-guide" / "reading.sqlite3"
        self.game = game
        self.places = tuple(row["id"] for row in book["route"]) if book else EARLY_PLACES[game]
        self.pages = CORE_PAGES[game] | set(self.places)
        self.sheet_stops = {name: row["stop"] for name, row in (book or {}).get("fieldSheets", {}).items()}
        self.pages.update(self.sheet_stops)
        if book:
            self.pages.update(row["id"] for row in book["articles"])
            self.pages.update(book.get("entities", {}))
        self.scope = json.dumps((game, revision, branch), ensure_ascii=True)

    def _connect(self, write: bool) -> sqlite3.Connection:
        db = plain_path(self.db)
        for ext in ("-journal", "-wal", "-shm"):
            plain_path(db.with_name(db.name + ext))
        if write:
            db.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(db.as_uri() + ("?mode=rwc" if write else "?mode=ro"), uri=True, timeout=0.3)
        try:
            if write:
                con.execute("CREATE TABLE IF NOT EXISTS markers (scope TEXT PRIMARY KEY, place INTEGER NOT NULL)")
                con.execute("CREATE TABLE IF NOT EXISTS pins (scope TEXT, article TEXT, PRIMARY KEY(scope, article))")
                con.execute("CREATE TABLE IF NOT EXISTS marked_pages (scope TEXT PRIMARY KEY, page TEXT NOT NULL)")
                con.execute("CREATE TABLE IF NOT EXISTS marked_areas (scope TEXT PRIMARY KEY, stop TEXT NOT NULL, sheet TEXT NOT NULL)")
            return con
        except BaseException:
            con.close()
            raise

    def read_bookmarks(self) -> tuple[int, str, list[str]]:
        if not plain_path(self.db).is_file():
            return -1, "", []
        with closing(self._connect(False)) as con:
            marker = con.execute("SELECT place FROM markers WHERE scope=?", (self.scope,)).fetchone()
            index = marker[0] if marker and marker[0] in (0, 1) else -1
            target = self.places[index] if index >= 0 else ""
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='marked_pages'").fetchone():
                saved = con.execute("SELECT page FROM marked_pages WHERE scope=?", (self.scope,)).fetchone()
                if saved:
                    target = saved[0]
                    stop = self.sheet_stops.get(target, target)
                    index = self.places.index(stop) if stop in self.places else -1
            if index >= 0 and con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='marked_areas'").fetchone():
                area = con.execute("SELECT sheet FROM marked_areas WHERE scope=? AND stop=?", (self.scope, self.places[index])).fetchone()
                if area and self.sheet_stops.get(area[0]) == self.places[index]:
                    target = area[0]
            rows = con.execute("SELECT article FROM pins WHERE scope=? ORDER BY article", (self.scope,))
            return index, target if index >= 0 else "", [row[0] for row in rows if row[0] in self.pages]

    def read(self) -> tuple[int, list[str]]:
        index, _, pins = self.read_bookmarks()
        return index, pins

    def set_place(self, place: int, sheet: str = "") -> None:
        if type(place) is not int or not 0 <= place < len(self.places):
            raise ValueError("Unknown guide location")
        if sheet and self.sheet_stops.get(sheet) != self.places[place]:
            raise ValueError("Unknown area at this guide location")
        with closing(self._connect(True)) as con, con:
            con.execute("INSERT INTO marked_pages VALUES (?,?) ON CONFLICT(scope) DO UPDATE SET page=excluded.page",
                        (self.scope, self.places[place]))
            if sheet:
                con.execute("INSERT INTO marked_areas VALUES (?,?,?) ON CONFLICT(scope) DO UPDATE SET stop=excluded.stop, sheet=excluded.sheet",
                            (self.scope, self.places[place], sheet))
            else:
                con.execute("DELETE FROM marked_areas WHERE scope=?", (self.scope,))
            con.execute("INSERT INTO markers VALUES (?,?) ON CONFLICT(scope) DO UPDATE SET place=excluded.place",
                        (self.scope, place if place < 2 else -1))

    def clear_place(self) -> None:
        with closing(self._connect(True)) as con, con:
            for table in ("marked_pages", "marked_areas", "markers"):
                con.execute(f"DELETE FROM {table} WHERE scope=?", (self.scope,))

    def toggle(self, article: str) -> None:
        if article not in self.pages:
            raise ValueError("Unknown guide entry")
        with closing(self._connect(True)) as con, con:
            con.execute("BEGIN IMMEDIATE")
            removed = con.execute("DELETE FROM pins WHERE scope=? AND article=?", (self.scope, article))
            if not removed.rowcount:
                con.execute("INSERT INTO pins VALUES (?,?)", (self.scope, article))


def _reviewed_photo(path: Path, expected: str) -> str:
    source = plain_path(path)
    if not source.is_file() or source.stat().st_size > 6 * 1024 * 1024:
        return ""
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        return ""
    if source.suffix == ".raw":
        if len(data) != 320 * 240 * 2:
            return ""
        image = QImage(data, 320, 240, 640, QImage.Format.Format_RGB555).copy()
    else:
        image = QImage.fromData(data)
    if image.isNull():
        return ""
    image = image.scaled(640, 480, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    encoded = QByteArray()
    buffer = QBuffer(encoded)
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, "PNG"):
        return ""
    return "data:image/png;base64," + base64.b64encode(bytes(encoded)).decode("ascii")


def _load_private(root: Path, game: str, revision: str, route: list) -> tuple[dict, dict, list[str]]:
    prefix = "iii" if game == "bof3" else "iv"
    photos = []
    for place in (0, 1):
        relative, expected = PLATES[f"{prefix}-{place}"]
        try:
            photos.append(_reviewed_photo(root / relative, expected))
        except (ValueError, OSError):
            photos.append("")
    if not re.fullmatch(r"[0-9a-f]{64}", revision):
        return {}, {}, photos
    try:
        directory = plain_path(root / "games" / game)
        receipt = plain_path(directory / "import-receipt.json")
        if receipt.stat().st_size > 4 * 1024**2:
            return {}, {}, photos
        record = json.loads(receipt.read_bytes())
        if (record.get("content_fingerprint") != revision or record.get("game") != game
                or not record.get("seed_entry_hashes_match")):
            return {}, {}, photos
        verified = open_imported_disc(directory, lambda: None)
        tables = progression.read_game_tables(verified)
        if tables["game"] != game:
            return {}, {}, photos
        floors = read_floors(verified, route)
        if game == "bof3":
            return tables, {"floors": floors, "genes": [{"name": name, "ap": tables["costs"][idx], "art": GENE_PLATES[idx]}
                                      for idx, name in enumerate(progression.GENES)]}, photos
        rows = []
        for idx, name in enumerate(progression.MASTERS):
            values = progression.master_comparison(tables, 0, idx)["second_modifier"]
            rows.append({"name": name if idx else "Unaffiliated", "stats": [values[key] for key in progression.STATS]})
        return tables, {"masters": rows, "floors": floors}, photos
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {}, {}, photos


class ApprovedPlates(QQuickImageProvider):
    """Serve already decoded local paintings on the first frame, without URL transport."""

    def __init__(self, css: str):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.images = {}
        for name, url in PLATE_PATTERN.findall(css):
            try:
                picture = QImage.fromData(base64.b64decode(url.split(",", 1)[1], validate=True), "WEBP")
            except binascii.Error:
                continue
            if not picture.isNull():
                self.images[name] = picture

    def requestImage(self, name, size, requested_size):
        picture = self.images.get(name, QImage())
        size.setWidth(picture.width())
        size.setHeight(picture.height())
        if requested_size.isValid() and not picture.isNull():
            return picture.scaled(requested_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return picture


class FieldGuideBridge(QObject):
    marksChanged = Signal()
    catalogueChanged = Signal()
    _loaded = Signal(object, object)

    def __init__(self, library: Callable[[], Path], resources: Path, parent: QObject | None = None):
        super().__init__(parent)
        self._library = library
        directory = resources / "design" / "field-guide"
        css = (directory / "plates.css").read_text(encoding="utf-8")
        wiki = directory / "wiki"
        self._books = {}
        for game in CORE_PAGES:
            try:
                self._books[game] = read_book(wiki, game)
            except (OSError, ValueError, TypeError, KeyError):
                pass
        self._book = {}
        try:
            css += (wiki / "illustrations.css").read_text(encoding="ascii")
        except (OSError, UnicodeError):
            pass
        self._captions = {}
        try:
            art_manifest = json.loads((wiki / "illustrations.json").read_text(encoding="utf-8"))
            self._captions = {plate["id"]: plate["description"] for sheet in art_manifest["sheets"]
                              for plate in sheet["plates"]}
        except (OSError, ValueError, TypeError, KeyError):
            pass
        self._plates = ApprovedPlates(css)
        self._diagrams = {}
        atlas = directory / "atlas"
        for name in ("cedar", "kurok", "dam"):
            sheet = atlas / (name + ".webp")
            source = atlas / (name + ".svg")
            if not (sheet.is_file() and source.is_file()):
                continue
            try:
                svg = ElementTree.parse(source).getroot()
                left, top, width, height = map(float, svg.attrib["viewBox"].split())
                pins = []
                for group in svg.iter("{http://www.w3.org/2000/svg}g"):
                    if "data-step" not in group.attrib:
                        continue
                    ring = group.find("{http://www.w3.org/2000/svg}circle")
                    if ring is None:
                        raise ValueError("Map pin has no centre")
                    x = (float(ring.attrib["cx"]) - left) / width
                    y = (float(ring.attrib["cy"]) - top) / height
                    if not (0 <= x <= 1 and 0 <= y <= 1):
                        raise ValueError("Map pin is outside the plate")
                    pins.append({"key": int(group.attrib["data-step"]), "x": x, "y": y})
                image = QImage(str(sheet))
                if image.isNull() or not pins:
                    continue
                self._plates.images["map-" + name] = image
                self._diagrams[name] = {"url": "image://chrysm/map-" + name,
                                        "pins": sorted(pins, key=lambda pin: pin["key"]), "ratio": width / height}
            except (OSError, ElementTree.ParseError, KeyError, ValueError, ZeroDivisionError):
                continue
        ridge = atlas / "kurok-wind.webp"
        if ridge.is_file():
            painting = QImage(str(ridge))
            if not painting.isNull():
                self._plates.images["kurok-wind"] = painting
                self._captions["kurok-wind"] = "Wind over the grass and red limestone ledges of Kurok ridge."
        self._floor_images = ApprovedPlates("")
        self._marks: ReadingMarks | None = None
        self._marker, self._mark_target, self._pins, self._error = -1, "", [], ""
        self._tables, self._catalog, self._photos = {}, {}, []
        self._selection: tuple | None = None
        self._cache: dict[tuple, tuple] = {}
        self._pending: dict[tuple, Future] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="field-guide")
        self._closed = False
        self._loaded.connect(self._accept, Qt.QueuedConnection)

    def install(self, engine):
        engine.addImageProvider("chrysm", self._plates)
        engine.addImageProvider("fieldfloor", self._floor_images)
        engine.rootContext().setContextProperty("fieldGuide", self)

    @Slot(str, result=str)
    def plate(self, name: str) -> str:
        return f"image://chrysm/{name}" if name in self._plates.images else ""

    @Slot(str, result=str)
    def caption(self, name: str) -> str:
        return self._captions.get(name, "")

    @Slot(str, result="QVariantMap")
    def routeDiagram(self, name: str) -> dict:
        return self._diagrams.get(name, {})

    @Property(int, notify=marksChanged)
    def marker(self):
        return self._marker

    @Property(str, notify=marksChanged)
    def markTarget(self):
        return self._mark_target

    @Property("QVariantList", notify=marksChanged)
    def pins(self):
        return self._pins

    @Property(str, notify=marksChanged)
    def message(self):
        return self._error

    @Property("QVariantMap", notify=catalogueChanged)
    def catalog(self):
        return self._catalog

    @Property("QVariantMap", notify=catalogueChanged)
    def book(self):
        return self._book

    @Property(str, notify=catalogueChanged)
    def floorStatus(self):
        if "floors" in self._catalog:
            return "ready"
        if self._selection and self._selection not in self._cache and re.fullmatch(r"[a-f0-9]{64}", self._selection[2]):
            return "loading"
        return "unavailable"

    @Property("QVariantList", notify=catalogueChanged)
    def photos(self):
        return self._photos

    def _refresh_marks(self):
        try:
            self._marker, self._mark_target, self._pins = self._marks.read_bookmarks()
            self._error = ""
        except (OSError, ValueError, sqlite3.Error):
            self._error = "Guide bookmarks could not be read from this library."
        self.marksChanged.emit()

    @Slot(str, str, int, result=str)
    def campaignPlace(self, game: str, place: str, floor: int) -> str:
        book = self._books.get(game, {})
        for stop in book.get("route", []):
            if stop["id"] == place:
                for area in stop.get("sectionsByArea", []):
                    if area["firstFloor"] == floor:
                        return area["name"]
                return stop["title"]
        return ""

    @Slot(str, str, str, result="QVariantMap")
    def campaignMark(self, game: str, revision: str, branch: str) -> dict[str, str]:
        book = self._books.get(game)
        if self._closed or not book:
            return {}
        try:
            marks = ReadingMarks(Path(self._library()), game, revision, branch, book)
            index, target, _ = marks.read_bookmarks()
        except (OSError, ValueError, sqlite3.Error):
            return {}
        if index < 0 or not target:
            return {}
        page = book.get("fieldSheets", {}).get(target) or book["route"][index]
        return {"id": target, "title": page["title"]}

    @Slot(str, str, str)
    def setContext(self, game: str, revision: str, branch: str):
        if self._closed or game not in CORE_PAGES:
            return
        root = Path(self._library())
        self._book = self._books.get(game, {})
        self._marks = ReadingMarks(root, game, revision, branch, self._book)
        self._marker, self._mark_target, self._pins = -1, "", []
        self._refresh_marks()
        receipt = root / "games" / game / "import-receipt.json"
        try:
            stamp = plain_path(receipt).stat().st_mtime_ns
        except (OSError, ValueError):
            stamp = 0
        key = (root, game, revision, stamp)
        self._selection = key
        self._tables, self._catalog, self._photos = self._cache.get(key, ({}, {}, []))
        self.catalogueChanged.emit()
        if key in self._cache or key in self._pending:
            return
        for old in list(self._pending):
            if self._pending[old].cancel():
                self._pending.pop(old, None)
        job = self._executor.submit(_load_private, root, game, revision, self._book.get("route", []))
        self._pending[key] = job
        job.add_done_callback(lambda future: self._complete(key, future))

    def _complete(self, key, future):
        if not self._closed and not future.cancelled():
            try:
                result = future.result()
            except Exception:
                result = ({}, {}, [])
            if not self._closed:
                self._loaded.emit(key, result)

    @Slot(object, object)
    def _accept(self, key, result):
        self._pending.pop(key, None)
        if self._closed:
            return
        for identifier, floor in result[1].get("floors", {}).items():
            data = base64.b64decode(floor["url"].split(",", 1)[1], validate=True)
            name = key[1] + "/" + identifier + "/" + hashlib.sha256(data).hexdigest()
            image = QImage.fromData(data, "PNG")
            if image.isNull():
                continue
            self._floor_images.images[name] = image
            floor["url"] = "image://fieldfloor/" + name
        if len(self._cache) >= 6:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = result
        if key == self._selection:
            self._tables, self._catalog, self._photos = result
            self.catalogueChanged.emit()

    @Slot(int)
    def setMarker(self, place: int):
        self._save(place=place)

    @Slot(int, str)
    def markArea(self, place: int, sheet: str):
        self._save(place=place, sheet=sheet)

    @Slot()
    def clearMarker(self):
        if self._marks:
            try:
                self._marks.clear_place()
            except (OSError, ValueError, sqlite3.Error):
                self._error = "Could not clear the marked place. Check the library is writable."
                self.marksChanged.emit()
            else:
                self._refresh_marks()

    @Slot(str)
    def togglePin(self, article: str):
        self._save(article=article)

    def _save(self, *, place: int | None = None, sheet: str = "", article: str = ""):
        if not self._marks:
            return
        try:
            if place is not None:
                self._marks.set_place(place, sheet)
            else:
                self._marks.toggle(article)
        except (OSError, ValueError, sqlite3.Error):
            self._error = "Could not save this bookmark. Check the library is writable."
            self.marksChanged.emit()
        else:
            self._refresh_marks()

    @Slot("QVariantList", result="QVariantMap")
    def combine(self, selection: list):
        return self.recipe(selection, [], False)

    @Slot("QVariantList", "QVariantList", bool, result="QVariantMap")
    def recipe(self, selection: list, allies: list, party_known: bool):
        if not self._marks or self._marks.game != "bof3" or not 1 <= len(selection) <= 3:
            return {}
        if any(type(value) is not int for value in selection) or len(set(selection)) != len(selection):
            return {}
        if self._tables:
            try:
                return progression.recipe_preview(self._tables, selection, allies if party_known else None)
            except ValueError:
                return {}
        return public_gene_recipe(selection)

    @Slot()
    def close(self):
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
