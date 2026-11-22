"""Exercise the shipped QML and reader store without any private game or firmware."""
from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path
import sqlite3
import time
from tempfile import TemporaryDirectory
import unittest

try:
    from PySide6.QtCore import QEventLoop, QMetaObject, QPointF, Qt, QUrl
    from PySide6.QtGui import QFontDatabase, QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtTest import QTest
    from shell.field_guide import FieldGuideBridge, ReadingMarks, _reviewed_photo
except ModuleNotFoundError as exc:
    if exc.name != "PySide6":
        raise
    QGuiApplication = None


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(QGuiApplication, "Field Guide rendering requires the Windows Player's PySide6 environment")
class NativeFieldGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["QT_QUICK_BACKEND"] = "software"
        if os.name == "nt":
            os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ["WINDIR"]) / "Fonts"))
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        if cls.app.platformName() != "offscreen":
            raise unittest.SkipTest("The native reader checks require an offscreen Qt process")
        for font in (ROOT / "design/field-guide/atlas/type").glob("*.ttf"):
            if QFontDatabase.addApplicationFont(str(font)) < 0:
                raise RuntimeError(f"Could not load the guide face {font.name}")

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.library = Path(temp.name)
        self.bridge = FieldGuideBridge(lambda: self.library, ROOT)
        self.engine = QQmlApplicationEngine()
        self.errors = []
        self.engine.warnings.connect(lambda errors: self.errors.extend(err.toString() for err in errors))
        self.bridge.install(self.engine)
        self.engine.load(QUrl.fromLocalFile(str(ROOT / "shell/qml/FieldGuide.qml")))
        self.assertTrue(self.engine.rootObjects(), self.errors)
        self.reader = self.engine.rootObjects()[0]
        self.win = QQuickWindow()
        self.win.resize(960, 700)
        self.reader.setParentItem(self.win.contentItem())
        self.reader.setWidth(960)
        self.reader.setHeight(700)
        self.win.show()
        self.win.requestActivate()
        self.pump()

    def tearDown(self):
        self.bridge.close()
        self.win.close()
        self.reader.setParentItem(None)
        self.engine.deleteLater()
        self.pump()
        self.assertEqual([], self.errors)

    def pump(self):
        # Layout polish and scene-graph callbacks run on a later animation frame.
        # An arbitrary number of processEvents() calls can all fit inside one frame.
        QTest.qWait(45)
        self.app.processEvents(QEventLoop.AllEvents, 10)

    def control(self, name, *, include_hidden=False):
        def find(item):
            if item.objectName() == name and (include_hidden or item.isVisible()):
                return item
            for child in item.childItems():
                hit = find(child)
                if hit is not None:
                    return hit
        item = find(self.reader)
        self.assertIsNotNone(item, name)
        return item

    def click(self, name):
        item = self.control(name)
        self.assertTrue(QMetaObject.invokeMethod(item, "click", Qt.DirectConnection), name)
        self.pump()

    def open(self, game, page="guide", branch="lab/test", rev="unregistered"):
        self.reader.openBook(game, rev, branch, page)
        self.pump()

    def test_search_finds_illustrated_areas_and_plain_keyboard_names(self):
        for game, term, destination in (("bof3","McNeil village","mcneil"), ("bof3","Mount Glaus","glaus"),
                ("bof4","Kyria Woods","kyria-woods"), ("bof4","Kyria village","kyria"), ("bof3","D'Lonzo","teacher-dlonzo"),
                ("bof4","Synesta Pathway","kyria-passage"), ("bof4","Kyria passage","kyria-passage"), ("bof4","Synesta","synesta"),
                ("bof4","Dam","dam"), ("bof4","Kurok","kurok"), ("bof3","Momo's Tower","momo-tower"),
                ("bof4","Bandit's Hideout","bandit-hideout"), ("bof4","Wyndia Castle Basement","wyndia-basement"),
                ("bof4","Mt. Grom","mt-glom"), ("bof4","Yaen","enemy.yaen")):
            with self.subTest(term=term):
                self.open(game)
                self.reader.setProperty("showLater", True)
                self.reader.setProperty("query", term)
                self.pump()
                rows = self.reader.searchRows().toVariant()
                self.assertEqual(destination, rows[0]["id"])
                self.click("entry" + destination)
                self.assertEqual(destination, self.reader.property("bookmarkId"))

    def test_saved_floor_and_explicit_area_choose_independently(self):
        for game, chapter, floor, sheet in (("bof3","cedar",7,"mcneil"),("bof4","dam-kyria",1045,"kyria-woods")):
            with self.subTest(sheet=sheet):
                self.reader.setProperty("gameStory", {"game":game,"place":chapter,"floorId":floor,"source":"Last in-game save"})
                self.open(game)
                self.assertEqual(sheet,self.reader.property("bookmarkId"))
                self.assertEqual(self.reader.property("area")["name"],self.bridge.campaignPlace(game,chapter,floor))
                self.open(game,"cedar" if game == "bof3" else "kyria")
                self.assertNotEqual(sheet,self.reader.property("bookmarkId"))

    def test_passage_bookmark_at_kyria_and_town_floor_are_distinct(self):
        self.reader.setProperty("gameStory", {"game":"bof4", "place":"dam-kyria", "floorId":4097})
        self.open("bof4", "wiki")
        self.reader.openSubject("Walkthrough")
        self.pump()
        self.click("wikikyria-passage")
        self.assertEqual("kyria-passage", self.reader.property("bookmarkId"))
        self.assertFalse(self.reader.isAvailable("synesta"))
        self.click("pinEntry")
        self.click("item.ammonia")
        self.assertFalse(self.reader.isAvailable("synesta"))
        self.reader.goBack()
        self.pump()
        self.assertEqual("kyria-passage", self.reader.property("bookmarkId"))
        self.open("bof4", "bookmarks")
        self.click("bookmarkkyria-passage")
        self.assertEqual("kyria-passage", self.reader.property("bookmarkId"))
        for map_id, expected in ((1032, "kyria-passage"), (4098, "synesta")):
            self.reader.setProperty("gameStory", {"game":"bof4", "place":"synesta", "floorId":map_id})
            self.open("bof4")
            self.assertEqual(expected, self.reader.property("bookmarkId"))
        self.open("bof4", "synesta")
        self.assertEqual("The children of Synesta", self.control("guidePageTitle").property("text"))

    def test_search_recipe_articles_and_direct_return(self):
        self.open("bof3")
        self.reader.setProperty("query", "elemental")
        self.pump()
        self.click("entryflame")
        self.assertEqual(self.reader.property("page"), "flame")
        self.click("pinEntry")
        self.assertEqual(self.bridge.pins, ["flame"])
        self.reader.visit("genes")
        self.pump()
        for i in range(3):
            self.click(f"gene{i}")
        self.assertEqual("15 initial AP", self.control("geneResult").property("text"))
        preview = self.bridge.combine([0, 1, 2])
        self.assertEqual((preview["cost"],preview["kind"],preview["form"]), (15,"special","Trygon"))
        self.assertEqual({}, self.bridge.combine([0, 0]))
        self.click("gene1")
        self.assertEqual("10 initial AP", self.control("geneResult").property("text"))
        returned = []
        self.reader.exitRequested.connect(lambda: returned.append(True))
        self.reader.setProperty("inSession", True)
        self.click("returnToGame")
        self.assertEqual(returned, [True])

    def test_pointer_changes_the_visible_dragon_result(self):
        self.open("bof3", "genes")
        for i, expected in enumerate(("Whelp", "Dragon", "Trygon")):
            item = self.control("gene"+str(i))
            centre = item.mapToScene(QPointF(item.width()/2,item.height()/2)).toPoint()
            QTest.mouseClick(self.win, Qt.LeftButton, Qt.NoModifier, centre)
            self.pump()
            self.assertTrue(item.property("selected"))
            self.assertEqual(expected, self.control("geneForm").property("text"))
        scroller = self.control("guideScroller")
        scroller.setProperty("contentY", scroller.property("contentHeight") - scroller.height())
        self.pump()
        result = self.control("geneForm")
        self.assertTrue(0 <= result.mapToScene(QPointF()).y() <= self.win.height() - result.height())

    def test_return_and_keypad_enter_activate_the_focused_gene(self):
        self.open("bof3", "genes")
        self.click("gene0")
        self.click("clearRecipe")
        flame = self.control("gene0")
        self.assertTrue(flame.hasActiveFocus())
        QTest.keyClick(self.win, Qt.Key_Return)
        self.pump()
        self.assertTrue(flame.property("selected"))
        QTest.keyClick(self.win, Qt.Key_Right)
        self.pump()
        frost = self.control("gene1")
        self.assertTrue(frost.hasActiveFocus())
        QTest.keyClick(self.win, Qt.Key_Enter)
        self.pump()
        self.assertTrue(frost.property("selected"))
        self.assertEqual("Dragon", self.control("geneForm").property("text"))

    def test_walkthrough_spoilers_and_branch_marks(self):
        self.open("bof4", "walk")
        self.assertEqual(self.reader.property("place"), 0)
        self.click("guideHint")
        self.assertTrue(self.reader.property("hintOpen"))
        self.assertFalse(self.reader.property("stepOpen"))
        self.click("guideReadAhead")
        self.assertEqual(self.reader.property("place"), 1)
        self.assertFalse(self.reader.property("hintOpen"))
        self.assertEqual(self.bridge.marker, -1)
        self.click("guideMark")
        self.click("pinEntry")
        self.open("bof4", "walk", "lab/another")
        self.assertEqual((self.bridge.marker, self.bridge.pins), (-1, []))
        self.open("bof3", "walk")
        self.assertEqual((self.bridge.marker, self.bridge.pins), (-1, []))
        self.open("bof4", "walk", rev="other revision")
        self.assertEqual((self.bridge.marker, self.bridge.pins), (-1, []))
        self.open("bof4", "walk")
        self.assertEqual((self.reader.property("place"), self.bridge.pins), (1, ["north-desert"]))
        self.assertEqual(list(self.library.iterdir()), [self.library / "lab"])

    def test_reopening_a_running_session_and_starting_another(self):
        self.reader.setProperty("gameRunning", True)
        self.reader.setProperty("inSession", True)
        self.open("bof3")
        self.click("entrygenes")
        self.click("gene1")
        self.open("bof3")
        self.assertEqual(self.reader.property("page"), "genes")
        self.assertEqual(self.control("geneResult").property("text"), "5 initial AP")
        self.open("bof4")
        self.assertEqual(self.reader.property("page"), "guide")
        self.click("entrywalk")
        self.click("guideReadAhead")
        self.click("guideMark")
        self.reader.setProperty("gameRunning", False)
        self.reader.setProperty("gameRunning", True)
        self.open("bof4")
        self.assertEqual(self.reader.property("page"), "walk")
        self.assertEqual(self.reader.property("place"), 1)

    def test_first_late_save_preserves_active_reading_until_another_visit(self):
        self.reader.setProperty("gameRunning", True)
        self.reader.setProperty("inSession", True)
        self.open("bof4")
        self.click("chooseStoryPlace")
        self.click("routeSpoilers")
        self.click("stopdam-kyria")
        self.click("routeAreaKurok")
        self.click("atlasPoint2")
        self.click("guideStep")
        self.click("guideHint")
        north = {"game": "bof4", "place": "north-desert", "source": "Last in-game save"}
        self.reader.setProperty("gameStory", north)
        for _ in range(2):
            self.open("bof4")
            self.assertEqual("kurok", self.reader.property("bookmarkId"))
            self.assertEqual(3, self.reader.property("selectedStep"))
            self.assertTrue(self.reader.property("stepOpen"))
            self.assertTrue(self.reader.property("hintOpen"))
            self.assertEqual(-1, self.bridge.marker)

        dam = {"game": "bof4", "place": "dam-kyria", "floorId": 1024,
               "source": "First visit", "visitKey": "g/1/250"}
        self.reader.setProperty("gameStory", dam)
        self.open("bof4")
        self.assertEqual("dam", self.reader.property("bookmarkId"))
        self.click("routeAreaKurok")
        self.click("atlasPoint2")
        self.reader.setProperty("gameStory", dam | {"visitKey": "g/2/400"})
        self.open("bof4")
        self.assertEqual("dam", self.reader.property("bookmarkId"))
        self.assertEqual(1, self.reader.property("selectedStep"))

        self.reader.setProperty("gameStory", {})
        self.open("bof4")
        self.assertEqual("guide", self.reader.property("page"))
        self.click("entrymasters")
        self.reader.setProperty("gameStory", north)
        self.open("bof4")
        self.assertEqual("north-desert", self.reader.property("bookmarkId"))

    def test_late_save_follows_without_a_reading_choice_and_across_scopes(self):
        self.reader.setProperty("gameRunning", True)
        self.reader.setProperty("inSession", True)
        self.open("bof4")
        self.assertEqual("guide", self.reader.property("page"))
        north = {"game": "bof4", "place": "north-desert", "source": "Last in-game save"}
        self.reader.setProperty("gameStory", north)
        self.open("bof4")
        self.assertEqual("north-desert", self.reader.property("bookmarkId"))

        self.reader.setProperty("gameStory", {})
        self.open("bof4", branch="lab/other")
        self.click("entrymasters")
        self.reader.setProperty("gameStory", north)
        self.open("bof4", branch="lab/other", rev="other revision")
        self.assertEqual("north-desert", self.reader.property("bookmarkId"))

        self.reader.setProperty("gameStory", {})
        self.open("bof4", branch="lab/third")
        self.click("entrymasters")
        self.reader.setProperty("gameRunning", False)
        self.reader.setProperty("gameRunning", True)
        self.reader.setProperty("gameStory", north)
        self.open("bof4", branch="lab/third")
        self.assertEqual("north-desert", self.reader.property("bookmarkId"))

    def test_explicit_mark_and_follow_save_during_a_running_session(self):
        self.reader.setProperty("gameRunning", True)
        self.reader.setProperty("inSession", True)
        self.open("bof4", "kurok")
        self.click("guideMark")
        self.click("followSave")
        north = {"game": "bof4", "place": "north-desert", "source": "Last in-game save"}
        self.reader.setProperty("gameStory", north)
        self.open("bof4")
        self.assertEqual("north-desert", self.reader.property("bookmarkId"))

        self.reader.visit("kurok")
        self.pump()
        self.click("guideMark")
        self.reader.setProperty("gameStory", {"game": "bof4", "place": "dam-kyria", "floorId": 1024,
                                              "source": "First visit", "visitKey": "g/1/250"})
        self.open("bof4")
        self.assertEqual("kurok", self.reader.property("bookmarkId"))
        self.click("followSave")
        self.assertEqual("dam", self.reader.property("bookmarkId"))
        self.assertEqual(-1, self.bridge.marker)

    def test_ledger_and_directional_controller_navigation(self):
        self.open("bof4", "masters")
        self.assertIn("Power -1", self.control("masterSummary").property("text"))
        self.reader.navigate("down")
        self.assertTrue(self.control("masterSlotA").hasActiveFocus())
        self.reader.navigate("right")
        self.assertTrue(self.control("masterSlotB").hasActiveFocus())
        self.reader.navigate("select")
        self.pump()
        self.assertTrue(self.control("masterChoice1").hasActiveFocus())
        self.reader.navigate("left")
        self.reader.navigate("select")
        self.pump()
        self.assertEqual("The six modifiers are identical.", self.control("masterSummary").property("text"))
        self.assertTrue(self.control("masterSlotB").hasActiveFocus())
        self.assertFalse(list(self.library.iterdir()))

    def test_art_and_small_layout(self):
        self.reader.setProperty("tv", True)
        self.reader.setWidth(670)
        self.open("bof3", "genes")
        image = self.control("guidePanorama")
        deadline = time.monotonic() + 3
        while image.property("sourceSize").width() == 0 and time.monotonic() < deadline:
            QTest.qWait(15)
        self.assertGreater(image.property("sourceSize").width(), 1000)
        for name in ("highlands", "sandsea", "flame", "frost", "thunder"):
            self.assertEqual(self.bridge.plate(name), "image://chrysm/" + name)
        self.assertEqual(self.bridge.plate("no-such-file"), "")
        self.assertLess(self.control("gene0").y(), self.control("gene1").y())
        self.assertLessEqual(self.control("guideScroller").property("contentWidth"), 670)
        src = self.library / "wrong.png"
        src.write_bytes(b"some other file")
        self.assertEqual(_reviewed_photo(src, "00"*32), "")

    def test_concurrent_pin_updates_and_rejection(self):
        first = ReadingMarks(self.library, "bof3", "v1", "lab/branch")
        second = ReadingMarks(self.library, "bof3", "v1", "lab/branch")
        first.toggle("genes")
        second.toggle("walk")
        self.assertEqual((first.read(), second.read()), ((-1, ["genes", "walk"]), (-1, ["genes", "walk"])))
        second.toggle("genes")
        first.set_place(1)
        self.assertEqual(first.read(), (1, ["walk"]))
        with self.assertRaises(ValueError):
            first.toggle("masters")
        with self.assertRaises(ValueError):
            first.set_place(-1)

    def test_recognised_save_manual_override_and_wiki_navigation(self):
        for game, location in (("bof3","cedar"), ("bof4","north-desert")):
            with self.subTest(game=game):
                self.reader.setProperty("gameStory", {"game": game, "place": location, "source": "Last in-game save"})
                self.open(game)
                self.assertEqual(("walk", 1), (self.reader.property("page"), self.reader.property("place")))
                self.assertEqual("LAST IN-GAME SAVE", self.control("storyEvidence").property("text"))
                book = self.bridge.book
                self.click("guideHint")
                self.click("guideStep")
                self.click("guideSources")
                self.assertTrue(self.reader.property("sourcesOpen"))
                self.click("guideRoute")
                self.assertFalse(self.reader.isAvailable(book["route"][-1]["id"]))
                self.click("routeSpoilers")
                self.click("stop" + book["route"][-1]["id"])
                self.click("pinEntry")
                self.click("guideMark")
                self.open(game)
                self.assertEqual(len(book["route"])-1, self.reader.property("place"))
                self.assertEqual("YOUR MARKED PLACE", self.control("storyEvidence").property("text"))
                self.click("followSave")
                self.assertEqual((-1, 1), (self.bridge.marker, self.reader.property("place")))
                self.click("guideIndex")
                self.click("entrywiki")
                self.click("category0")
                chosen = self.reader.property("category")
                article = next(a for a in book["articles"] if a["category"] == chosen and self.reader.isAvailable(a["id"]))
                self.click("wiki" + article["id"])
                self.assertEqual(article["title"], self.control("guidePageTitle").property("text"))
                self.reader.goBack()
                self.assertEqual(("wiki", chosen), (self.reader.property("page"), self.reader.property("category")))
                self.reader.goBack()
                self.assertEqual("", self.reader.property("category"))
                self.open(game, "walk", "lab/fresh")
                self.assertEqual(self.bridge.pins, [])

    def test_legacy_markers_and_pins_survive_stable_page_migration(self):
        from shell.guide_book import read_book
        book = read_book(ROOT / "design/field-guide/wiki", "bof3")
        marks = ReadingMarks(self.library, "bof3", "rev", "lab/old", book)
        marks.db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(marks.db)) as db, db:
            db.execute("CREATE TABLE markers(scope TEXT PRIMARY KEY, place INTEGER)")
            db.execute("CREATE TABLE pins(scope TEXT, article TEXT, PRIMARY KEY(scope,article))")
            db.execute("INSERT INTO markers VALUES(?,1)", (marks.scope,))
            db.execute("INSERT INTO pins VALUES(?, 'walk')", (marks.scope,))
        self.assertEqual((1, ["walk"]), marks.read())
        marks.set_place(3)
        rearranged = book | {"route": [*book["route"][:2], book["route"][3], book["route"][2], *book["route"][4:]]}
        reordered = ReadingMarks(self.library, "bof3", "rev", "lab/old", rearranged)
        self.assertEqual((2, ["walk"]), reordered.read())
        reordered.clear_place()
        self.assertEqual((-1, ["walk"]), marks.read())

    def test_dam_arrival_opens_its_directions_and_section_switch_preserves_branch(self):
        self.reader.setProperty("gameStory", {"game":"bof4","place":"dam-kyria","floorId":1024,"source":"First visit"})
        self.open("bof4")
        evidence = self.control("storyEvidence")
        self.assertEqual("FIRST VISIT", evidence.property("text"))
        self.assertEqual("The Dam", self.control("guidePageTitle").property("text"))
        self.assertEqual(self.bridge.book["fieldSheets"]["dam"]["mapTitle"], self.control("routeLandmark").property("text"))
        self.assertTrue(self.reader.property("hasWarning"))
        self.click("guideStep")
        self.click("routeAreaKurok")
        self.assertFalse(evidence.isVisible())
        self.assertFalse(self.reader.property("hasWarning"))
        self.assertEqual("Kurok ridge", self.control("guidePageTitle").property("text"))
        self.assertEqual(self.bridge.book["fieldSheets"]["kurok"]["mapTitle"], self.control("routeLandmark").property("text"))
        self.assertEqual(-1, self.bridge.marker)
        self.click("routeAreaKyria")
        self.assertFalse(evidence.isVisible())
        self.assertEqual(self.bridge.book["fieldSheets"]["kyria"]["mapTitle"], self.control("routeLandmark").property("text"))
        self.click("routeAreaDam")
        self.assertTrue(evidence.isVisible())
        self.assertEqual("FIRST VISIT", evidence.property("text"))

    def test_landmark_map_item_search_bestiary_and_optional_lore(self):
        cases = [("bof3", "cedar", "Skill Ink", "Goblin"), ("bof4", "dam-kyria", "Deep Diver", "Scorpion")]
        for game, stop, item, enemy in cases:
            with self.subTest(game=game):
                self.reader.setProperty("gameStory", {"game": game, "place": stop, "source": "Last in-game save"})
                self.open(game)
                self.assertEqual("Map", self.reader.property("activeSection"))
                self.click("atlasPoint2")
                self.assertEqual(3, self.reader.property("selectedStep"))
                self.assertTrue(self.control("routeDirection3").property("selected"))
                self.click("routeDirection2")
                self.assertEqual(2, self.reader.property("selectedStep"))
                self.assertFalse(self.reader.property("loreOpen"))
                self.click("workedLore")
                self.assertTrue(self.reader.property("loreOpen"))
                item_id = "item." + item.lower()
                self.click(item_id)
                self.assertEqual(item_id, self.reader.property("page"))
                self.assertEqual(item, self.control("guidePageTitle").property("text"))
                self.click("pinEntry")
                self.reader.goBack()
                self.pump()
                self.assertTrue(self.reader.property("loreOpen"))
                self.assertEqual(2, self.reader.property("selectedStep"))
                self.click("guideIndex")
                self.reader.setProperty("query", item)
                self.pump()
                self.assertTrue(self.control("entry"+item_id).isVisible())
                self.click("entry" + stop + "-items")
                self.assertIn(item_id, self.bridge.pins)
                self.click(item_id)
                self.assertEqual(item_id, self.reader.property("page"))
                self.assertEqual(-1, self.bridge.marker)
                if game == "bof4":
                    self.reader.setWidth(555)
                    self.reader.setProperty("tv", True)
                    self.reader.visit(stop)
                    self.pump()
                    self.click("enemy." + enemy.lower())
                    self.assertEqual(enemy, self.control("guidePageTitle").property("text"))
                    self.assertLessEqual(self.control("guideScroller").property("contentWidth"), 555)
        self.reader.setProperty("gameStory", {})
        self.open("bof4", "guide", "lab/unknown")
        self.reader.setProperty("query", "Deep Diver")
        self.pump()
        self.assertFalse(self.reader.isAvailable("dam-kyria-items"))
        self.assertFalse(self.reader.isAvailable("dam-kyria-encounters"))

    def test_area_mark_and_pin_restore_exact_spread_and_do_not_rewrite_story_evidence(self):
        self.open("bof4", "kurok")
        self.click("guideReadAhead")
        self.assertEqual("The Dam", self.control("guidePageTitle").property("text"))
        self.click("guideMark")
        self.click("pinEntry")
        self.assertEqual("dam", self.bridge.markTarget)
        self.assertEqual(["dam"], self.bridge.pins)
        self.open("bof4", "guide", "lab/other")
        self.assertEqual("", self.bridge.markTarget)
        self.open("bof4")
        self.assertEqual("The Dam", self.control("guidePageTitle").property("text"))
        self.reader.visit("bookmarks")
        self.pump()
        self.click("bookmarkdam")
        self.assertEqual("dam", self.reader.property("bookmarkId"))
        with closing(sqlite3.connect(self.library / "lab/field-guide/reading.sqlite3")) as store:
            self.assertEqual(("dam-kyria",), store.execute("SELECT page FROM marked_pages").fetchone())
        self.click("followSave")
        self.assertEqual("", self.bridge.markTarget)

    def test_campaign_reads_only_the_marked_revision_and_branch_without_opening_the_reader(self):
        from unittest.mock import patch
        from shell.guide_book import read_book

        book = read_book(ROOT / "design/field-guide/wiki", "bof4")
        chapter = next(i for i,row in enumerate(book["route"]) if row["id"] == "dam-kyria")
        with patch.object(self.bridge._executor, "submit", side_effect=AssertionError("A mark lookup started disc inspection")):
            self.assertEqual({}, self.bridge.campaignMark("bof4", "original", "lab/one"))
            self.assertEqual([], list(self.library.iterdir()))
            first = ReadingMarks(self.library, "bof4", "original", "lab/one", book)
            other = ReadingMarks(self.library, "bof4", "original", "lab/two", book)
            first.set_place(chapter, "dam")
            other.set_place(chapter, "kurok")
            self.assertEqual({"id":"dam","title":"The Dam"}, self.bridge.campaignMark("bof4", "original", "lab/one"))
            self.assertEqual({"id":"kurok","title":"Kurok ridge"}, self.bridge.campaignMark("bof4", "original", "lab/two"))
            self.assertEqual({}, self.bridge.campaignMark("bof3", "original", "lab/one"))
            self.assertEqual({}, self.bridge.campaignMark("bof4", "other", "lab/one"))
            self.assertEqual({}, self.bridge.campaignMark("bof4", "original", "play/one"))
            self.assertFalse((self.library / "play").exists())
            self.assertEqual(-1, self.bridge.marker)
            first.set_place(0)
            self.assertEqual({"id":book["route"][0]["id"],"title":book["route"][0]["title"]},
                             self.bridge.campaignMark("bof4", "original", "lab/one"))
            first.clear_place()
            self.assertEqual({}, self.bridge.campaignMark("bof4", "original", "lab/one"))

    def test_worked_page_contours_full_directions_and_teacher_lessons(self):
        for game, sheet, title in (("bof3", "cedar", "Cedar Woods"), ("bof3", "mcneil", "McNeil village"),
                ("bof3", "glaus", "Mt. Glaus"), ("bof4", "kyria", "Kyria village"), ("bof4", "kyria-woods", "Kyria Woods"),
                ("bof4", "kyria-passage", "The passage to Synesta"), ("bof4", "kurok", "Kurok ridge"), ("bof4", "dam", "The Dam")):
            with self.subTest(sheet=sheet):
                self.open(game, sheet)
                self.assertEqual(title, self.control("guidePageTitle").property("text"))
                opening = self.bridge.book["fieldSheets"][sheet].get("opening")
                toggle = self.control("damEngines", include_hidden=True)
                self.assertEqual(bool(opening), toggle.isVisible())
                if opening:
                    self.assertEqual(opening["title"], toggle.property("text"))
                    self.click("damEngines")
                    self.assertIn(opening["steps"][0], self.control("routeOpeningStep1").property("text"))
                    self.click("damEngines")
                if sheet == "cedar":
                    self.assertFalse(self.control("afterCedar", include_hidden=True).isVisible())
                diagram = self.bridge.routeDiagram(sheet)
                pins = [p["key"] for p in diagram["pins"]]
                self.assertEqual([s["key"] for s in self.bridge.book["fieldSheets"][sheet]["steps"]], pins)
                self.assertGreater(self.control("routeIllustration").property("sourceSize").width(), 1000)
                self.click("expandRouteMap")
                self.assertTrue(self.reader.property("routeExpanded"))
                self.assertFalse(self.reader.property("mapExpanded"))
                self.click("guideStep")
                for step in self.bridge.book["fieldSheets"][sheet]["steps"]:
                    self.assertIn(step["body"], self.control("routeDirection"+str(step["key"])).property("detail"))
        self.click("damEngines")
        self.assertTrue(self.reader.property("enginesOpen"))
        self.open("bof4", "kurok")
        self.click("relatedteacher-rwolf")
        table = self.control("referenceTable0").property("dataTable")
        self.assertIn(["20 hits", "Flame Pillar"], table["rows"])
        self.reader.setProperty("gameStory", {"game":"bof4","place":"dam-kyria","source":"First visit"})
        self.open("bof4", "masters")
        lessons = self.control("lessonsteacher-rwolf").property("dataTable")
        if hasattr(lessons, "toVariant"):
            lessons = lessons.toVariant()
        self.assertEqual(table["rows"], lessons["rows"])
        self.click("trainingteacher-rwolf")
        self.assertEqual("teacher-rwolf", self.reader.property("page"))
        self.click("relatedcombination-magic")
        self.assertTrue(self.control("referenceTable0").isVisible())

    def test_reader_reflows_visible_text_and_tables_without_cutting_off_labels(self):
        def inspect(item, width):
            if not item.isVisible():
                return
            caption = item.property("text")
            if isinstance(caption, str) and caption and item.property("lineCount") is not None and item.width() > 4 and item.height() > 2:
                position = item.mapToScene(QPointF())
                self.assertGreaterEqual(position.x(), -2, caption)
                self.assertLessEqual(position.x() + item.width(), width+2, caption)
                self.assertLessEqual(item.property("contentWidth"), item.width()+2, caption)
                self.assertLessEqual(item.property("contentHeight"), item.height()+2, caption)
            for child in item.childItems():
                inspect(child, width)

        for width, tv in ((555, True), (960, False), (1260, False)):
            self.win.resize(width, 700)
            self.reader.setWidth(width)
            self.reader.setProperty("tv", tv)
            for game, page in (("bof3","cedar"),("bof4","kurok"),("bof4","dam"),("bof4","teacher-rwolf"),
                               ("bof4","combination-magic"),("bof3","genes"),("bof4","masters"),("bof4","wiki")):
                with self.subTest(width=width, game=game, page=page):
                    self.open(game, page)
                    if page in ("cedar", "kurok", "dam"):
                        for state in ("stepOpen", "readingFloor", "enginesOpen"):
                            self.reader.setProperty(state, True)
                        self.pump()
                    inspect(self.reader, width)

    def test_offline_roster_preserves_lessons_and_spoiler_controls(self):
        self.open("bof4", "masters")
        teachers = self.bridge.book["teachers"]
        self.click("revealMasters")
        self.click("masterSlotB")
        later = next(i for i,t in enumerate(teachers, 1) if t["name"] == "Momo")
        self.click("masterChoice" + str(later))
        self.assertEqual("Momo", self.control("masterSlotB").property("text"))
        source = next(t for t in teachers if t["name"] == "Momo")
        rows = self.reader.property("allMasters").toVariant()
        self.assertEqual([source["growth"][k] for k in ("HP","AP","power","defence","agility","wisdom")],
                         next(r["stats"] for r in rows if r["name"] == "Momo"))
        self.assertTrue(self.control("lessonsteacher-momo").isVisible())
        self.click("revealMasters")
        self.assertEqual("Rwolf", self.control("masterSlotB").property("text"))

    def test_controller_reads_long_articles_before_reaching_related_links(self):
        self.reader.setWidth(555)
        self.reader.setHeight(505)
        self.reader.setProperty("tv", True)
        for game in ("bof3", "bof4"):
            with self.subTest(game=game):
                self.open(game)
                longest = max(self.bridge.book["articles"], key=lambda row: sum(len(s["text"]) for s in row["sections"]))
                self.open(game, longest["id"])
                scroller = self.control("guideScroller")
                self.assertEqual(0, scroller.property("contentY"))
                self.reader.navigate("down")
                self.pump()
                y = scroller.property("contentY")
                self.assertGreater(y, 0)
                self.assertLessEqual(y, scroller.height() * 0.66)
                self.reader.navigate("up")
                self.assertLess(scroller.property("contentY"), y)
                for _ in range(32):
                    self.reader.navigate("down")
                    if not self.control("guidePageTitle").hasActiveFocus():
                        break
                self.assertFalse(self.control("guidePageTitle").hasActiveFocus())

    def test_subject_index_is_visible_before_story_names_are_revealed(self):
        self.open("bof4", "wiki")
        self.assertTrue(self.control("category4").isVisible())
        self.reader.openSubject("Dragons")
        self.pump()
        self.assertFalse(self.reader.isAvailable("dragon-pilgrimage"))
        self.click("revealSubject")
        self.assertTrue(self.reader.isAvailable("dragon-pilgrimage"))
        self.assertFalse(self.reader.isAvailable("meeting"))
        self.click("wikidragon-pilgrimage")
        self.assertEqual(self.reader.property("page"), "dragon-pilgrimage")
