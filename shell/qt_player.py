"""Native Qt Quick Player. Start with python -m shell.qt_player."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time


def main(argv=None, on_loaded=None):
    from PySide6.QtCore import QObject, Property, QStandardPaths, QTimer, QUrl, Signal, Slot
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QFileDialog
    from PySide6.QtQml import QQmlApplicationEngine
    from shell.field_guide import FieldGuideBridge
    from shell.service import PlayerService

    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--library", type=Path)
    arguments.add_argument("--channel", choices=("play", "lab"))
    arguments.add_argument(
        "--review", type=Path, help="Write a native offscreen view and exit."
    )
    arguments.add_argument(
        "--view",
        choices=("Journey", "Field guide", "Library & setup", "Controls", "Recovery", "Workshop", "Lab"),
        default="Journey",
    )
    arguments.add_argument("--title", choices=("bof3", "bof4"))
    arguments.add_argument("--guide-entry", help="Choose a Field Guide page for an offscreen render.")
    arguments.add_argument("--expect-saved-place", help=argparse.SUPPRESS)
    arguments.add_argument("--record-guide-opening", action="store_true", help=argparse.SUPPRESS)
    arguments.add_argument("--size", default="1160x760")
    args = arguments.parse_args(argv)
    if args.guide_entry and not (args.review and args.view == "Field guide" and args.title):
        arguments.error("--guide-entry requires --review, --view 'Field guide' and --title")
    if (args.expect_saved_place or args.record_guide_opening) and (
            args.guide_entry or not args.review or args.view != "Field guide" or args.channel != "lab"):
        arguments.error("The saved-place check needs an automatic offscreen Field Guide opening in Lab")
    if args.review:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["QT_QUICK_BACKEND"] = "software"
        if sys.platform == "win32":
            os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ["WINDIR"]) / "Fonts"))
    app = QApplication([sys.argv[0]])
    app.setApplicationName("BoF Atelier")
    app.setOrganizationName("BoF Atelier")
    repeat_filter = None
    if sys.platform == "win32":
        from ctypes.wintypes import MSG
        from PySide6.QtCore import QAbstractNativeEventFilter

        class EnterRepeatFilter(QAbstractNativeEventFilter):
            def nativeEventFilter(self, event_type, message):
                if event_type == b"windows_generic_MSG":
                    event = MSG.from_address(int(message))
                    # Qt can lose repeat tracking when the game hands focus
                    # back to the launcher. Use the original WM_KEYDOWN flag.
                    if event.message == 0x0100 and event.wParam == 0x0D and event.lParam & (1 << 30):
                        return True, 0
                return False, 0

        repeat_filter = EnterRepeatFilter()
        app.installNativeEventFilter(repeat_filter)
    service = PlayerService(args.library, channel=args.channel)
    if args.review:
        # Rendering a requested view uses in-memory view selection only.
        service.page = args.view
        if args.title:
            service.game = args.title
            service.refresh()
        if args.guide_entry:
            from shell.guide_book import CORE_PAGES, read_book
            wiki = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "design/field-guide/wiki"
            chosen = read_book(wiki, args.title)
            pages = {row["id"] for row in chosen["route"] + chosen["articles"]}
            pages.update(chosen.get("fieldSheets", {}))
            if args.guide_entry not in pages | CORE_PAGES[args.title] | {"guide", "wiki", "route"}:
                arguments.error("Unknown Field Guide page for this title")
        if args.view == "Field guide":
            service.action("openGuide", args.guide_entry or "guide")
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    atlas = root / "design/field-guide/atlas"
    for name in ("Gloock-Regular.ttf", "BarlowSemiCondensed-SemiBold.ttf"):
        QFontDatabase.addApplicationFont(str(atlas / "type" / name))
    from shell.menu_sound import MenuSound
    sound = MenuSound(atlas / "sound")
    allow_menu_audio = not args.review and app.platformName() != "offscreen"
    app.aboutToQuit.connect(sound.close)

    class Bridge(QObject):
        changed = Signal()
        move = Signal(str)
        returned = Signal()

        def __init__(self):
            super().__init__()
            self.seen = -1
            self.locations = {}

        @Property(str, notify=changed)
        def model(self):
            return json.dumps(service.snapshot(), ensure_ascii=False)

        @Slot(str, str, result=str)
        def perform(self, name, value):
            try:
                if name == "auditionMusic":
                    sound.update(service, audible=allow_menu_audio, audition=True)
                    return ""
                result = service.action(name, json.loads(value))
                if name == "menuMusic" and not service.settings.get("menu_music"):
                    sound.stop()
                sound.update(service, audible=allow_menu_audio)
                if name == "assetPreview":
                    return json.dumps(result, ensure_ascii=False)
            except Exception as exc:
                service.message = str(exc) or type(exc).__name__
                if name in ("openGuide", "returnToGame"):
                    service.guide_error = service.message
                service.version += 1
            self.changed.emit()
            return ""

        @Slot(str)
        def pick(self, mode):
            documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
            downloads = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
            start = self.locations.get(mode, documents or str(Path.home()))
            if mode == "archive":
                incoming = service.root / "incoming"
                start = self.locations.get(mode, str(incoming) if incoming.is_dir() else start)
                files, _ = QFileDialog.getOpenFileNames(
                    None,
                    "Add games",
                    start,
                    "Game archives and CUE files (*.7z *.zip *.cue);;All files (*)",
                )
                if files:
                    self.locations[mode] = str(Path(files[0]).parent)
                    self.perform("import", json.dumps(files))
            elif mode == "existingRuntime":
                filename, _ = QFileDialog.getOpenFileName(
                    None,
                    "Choose a compatible DuckStation executable",
                    start,
                    "Windows applications (*.exe)",
                )
                if filename:
                    self.perform(mode, json.dumps(filename))
            elif mode in ("runtimePackage", "reduxPackage", "labPackage"):
                filename, _ = QFileDialog.getOpenFileName(
                    None,
                    "Choose the unchanged official package",
                    self.locations.get(mode, downloads or start),
                    "Official ZIP packages (*.zip)",
                )
                if filename:
                    self.locations[mode] = str(Path(filename).parent)
                    self.perform(mode, json.dumps(filename))
            elif mode == "firmware":
                filename, _ = QFileDialog.getOpenFileName(
                    None,
                    "Select a local PlayStation BIOS",
                    start,
                    "Firmware (*.bin *.rom *.bios *.zip);;All files (*)",
                )
                if filename:
                    self.locations[mode] = str(Path(filename).parent)
                    self.locations["discover"] = self.locations[mode]
                    self.perform("firmware", json.dumps(filename))
            else:
                prompts = {
                    "library": "Open a private Atelier library",
                    "discover": "Search this folder for firmware",
                    "capture": "Select closed-game save files to back up",
                }
                if mode in prompts:
                    folder = QFileDialog.getExistingDirectory(None, prompts[mode], start)
                    if folder:
                        self.locations[mode] = folder
                        self.perform(mode, json.dumps(folder))

        @Slot("QVariantList", str)
        def dropped(self, urls, mode):
            files = [
                (entry if isinstance(entry, QUrl) else QUrl(str(entry))).toLocalFile()
                for entry in urls
            ]
            files = [p for p in files if p]
            if files:
                self.perform(
                    "firmware" if mode == "firmware" else "import",
                    json.dumps(files[0] if mode == "firmware" else files),
                )

        @Slot()
        def tick(self):
            try:
                event = service.poll()
                if self.seen != event["version"]:
                    self.seen = event["version"]
                    sound.update(service, audible=allow_menu_audio)
                    self.changed.emit()
                if event["move"]:
                    self.move.emit(event["move"])
                if event["returned"]:
                    self.returned.emit()
            except Exception as exc:
                if service.message != str(exc):
                    service.message = str(exc)
                    if service.process is not None:
                        service.guide_error = service.message
                    service.version += 1
                    self.changed.emit()

    bridge = Bridge()
    reader = FieldGuideBridge(lambda: service.root, root, parent=app)
    engine = QQmlApplicationEngine()
    system_reduced_motion = False
    if sys.platform == "win32":
        import ctypes
        animations = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(animations), 0):
            system_reduced_motion = not animations.value
    engine.rootContext().setContextProperty("systemReducedMotion", system_reduced_motion)
    engine.rootContext().setContextProperty("player", bridge)
    reader.install(engine)
    engine.load(QUrl.fromLocalFile(str(root / "shell/qml/Main.qml")))
    if not engine.rootObjects():
        reader.close()
        service.close()
        return 2
    window = engine.rootObjects()[0]
    if not isinstance(window, QQuickWindow):
        reader.close()
        service.close()
        return 2
    if sys.platform == "win32" and app.platformName() == "windows":
        service.player_hwnd = int(window.winId())
    if on_loaded is not None:
        QTimer.singleShot(20, lambda: on_loaded(app, window, bridge))
    timer = QTimer()
    timer.setInterval(45)
    timer.timeout.connect(bridge.tick)
    timer.start()
    status = [0]
    if args.review:
        width, height = map(int, args.size.split("x"))
        window.resize(width, height)
        deadline = time.monotonic() + 12

        def render():
            waiting_for_disc = (args.view == "Field guide" and reader.floorStatus == "loading")
            if (not window.property("artworkReady") or waiting_for_disc) and time.monotonic() < deadline:
                QTimer.singleShot(80, render)
                return
            try:
                if args.guide_entry and args.guide_entry != "guide":
                    view = window.findChild(QObject, "fieldGuideReader")
                    actual = (view.property("page"), view.property("pinId"), view.property("bookmarkId")) if view else ()
                    if args.guide_entry not in actual:
                        raise ValueError(f"Expected guide page {args.guide_entry}, rendered {actual}")
                if args.expect_saved_place or args.record_guide_opening:
                    view = window.findChild(QObject, "fieldGuideReader")
                    title = view.findChild(QObject, "guidePageTitle") if view else None
                    evidence = view.findChild(QObject, "storyEvidence") if view else None
                    if not title or not evidence or not view.isVisible():
                        raise ValueError("The Field Guide did not open")
                    opening = {"game": view.property("game"), "page": view.property("page"),
                               "entry": view.property("pinId"), "title": title.property("text"),
                               "label": evidence.property("text") if evidence.isVisible() else "",
                               "manual_marker": reader.marker >= 0}
                    if args.expect_saved_place and (
                            opening["page"] != "walk" or opening["entry"] != args.expect_saved_place
                            or service.guide_story.get("place") != args.expect_saved_place
                            or opening["manual_marker"] or opening["label"] != "LAST IN-GAME SAVE"):
                        raise ValueError("The rendered page did not come from the expected ordinary save")
                image = window.grabWindow()
                args.review.parent.mkdir(parents=True, exist_ok=True)
                if not window.property("artworkReady") or image.isNull() or not image.save(str(args.review)):
                    status[0] = 3
                elif args.record_guide_opening:
                    from tools.local_store import atomic_bytes
                    atomic_bytes(args.review.with_suffix(".guide.json"), json.dumps(opening, indent=2).encode("utf-8"))
            except (OSError, RuntimeError, ValueError, AttributeError) as exc:
                print(str(exc), file=sys.stderr)
                status[0] = 3
            finally:
                app.quit()

        QTimer.singleShot(800, render)
    try:
        app.exec()
    finally:
        timer.stop()
        if repeat_filter is not None:
            app.removeNativeEventFilter(repeat_filter)
        reader.close()
        service.close()
    return status[0]


def run(argv: list[str]) -> int:
    """A failed offscreen review reports to its caller without invoking the windowed bootloader's error UI."""
    review = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    review.add_argument("--review", type=Path)
    request, _ = review.parse_known_args(argv)
    if request.review is None:
        return main(argv)
    try:
        return main(argv)
    except Exception as error:
        message = f"{type(error).__name__}: {error}"[:2048]
        try:
            request.review.with_suffix(".error.txt").write_text(message + "\n", encoding="utf-8")
        except (OSError, ValueError):
            pass
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        return 3


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(run(sys.argv[1:]))
