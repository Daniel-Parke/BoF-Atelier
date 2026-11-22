"""Capture closed PS1 campaigns, exchange snapshots and restore to new Lab branches."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager, nullcontext
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import uuid
import zipfile

try:
    from .local_store import StoreError, canonical_bytes, fingerprint, member_path, plain_path
except ImportError:
    from local_store import StoreError, canonical_bytes, fingerprint, member_path, plain_path


MAX_FILE = 96 * 1024**2
MAX_TOTAL = 384 * 1024**2
MAX_FILES = 512


def _kind(path: Path) -> str | None:
    name = path.name.lower()
    if path.suffix.lower() in {".mcd", ".mcr", ".mc", ".srm"}:
        return "card"
    if path.suffix.lower() in {".sav", ".state"} or ".sav." in name or ".state." in name:
        return "state"
    return None


def _files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise StoreError("Select the save directory of a closed runtime.")
    results = []
    total = 0
    for count, path in enumerate(folder.rglob("*"), start=1):
        if count > 20_000:
            raise StoreError("Choose a specific save or memory-card directory.")
        plain_path(path)
        if not _kind(path) or not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if not 0 < size <= MAX_FILE or total > MAX_TOTAL or len(results) >= MAX_FILES:
            raise StoreError("Save selection exceeds snapshot limits or contains an empty file.")
        results.append(path)
    if not results:
        raise StoreError("No cards or runtime states found in the selected directory.")
    return sorted(results)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lock_id(lock: dict | str) -> str:
    if isinstance(lock, dict) and lock:
        return fingerprint(lock)
    if isinstance(lock, str) and re.fullmatch("[0-9a-f]{64}", lock):
        return lock
    raise StoreError("An edition lock or its full SHA-256 is required.")


def _validate_point(point: dict) -> None:
    if not isinstance(point, dict) or point.get("schema_version") != 1:
        raise StoreError("Unknown snapshot schema.")
    if not re.fullmatch("[0-9a-f]{32}", str(point.get("id", ""))):
        raise StoreError("Invalid snapshot identifier.")
    if point.get("parent") is not None and not re.fullmatch("[0-9a-f]{32}", str(point["parent"])):
        raise StoreError("Invalid snapshot parent.")
    if point.get("parent") == point["id"] or point.get("game") not in {"bof3", "bof4"}:
        raise StoreError("Invalid game or cyclic snapshot parent.")
    if point.get("channel") not in {"play", "lab"} or not isinstance(point.get("campaign"), str):
        raise StoreError("Invalid campaign or channel.")
    if not 0 < len(point["campaign"]) <= 160 or not isinstance(point.get("created_utc"), str):
        raise StoreError("Invalid campaign label or timestamp.")
    if datetime.fromisoformat(point["created_utc"]).tzinfo is None:
        raise StoreError("Snapshot time requires a time zone.")
    if not isinstance(point.get("edition_lock"), str) or _lock_id(point["edition_lock"]) != point["edition_lock"]:
        raise StoreError("Invalid edition fingerprint.")
    files = point.get("files")
    if not isinstance(files, list) or not 0 < len(files) <= MAX_FILES:
        raise StoreError("Invalid snapshot file count.")
    seen = set()
    total = 0
    for file in files:
        if not isinstance(file, dict) or not isinstance(file.get("path"), str):
            raise StoreError("Invalid snapshot file entry.")
        name = member_path(file["path"])
        if (name.casefold() in seen or file.get("kind") not in {"card", "state"}
                or _kind(Path(name)) != file["kind"] or type(file.get("bytes")) is not int
                or not 0 < file["bytes"] <= MAX_FILE
                or not re.fullmatch("[0-9a-f]{64}", str(file.get("sha256", "")))):
            raise StoreError("Invalid file identity or conflicting snapshot path.")
        seen.add(name.casefold())
        total += file["bytes"]
    if total > MAX_TOTAL:
        raise StoreError("Snapshot exceeds the byte budget.")


class CampaignStore:
    def __init__(self, private_root: Path):
        self.private = plain_path(private_root)
        self.directory = plain_path(self.private / "atelier")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = plain_path(self.directory / "campaigns.sqlite3")
        with self._transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS content (digest TEXT PRIMARY KEY, body BLOB NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS points (id TEXT PRIMARY KEY, game TEXT NOT NULL, manifest TEXT NOT NULL)")

    @contextmanager
    def _transaction(self):
        with closing(sqlite3.connect(self.database, timeout=15)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def history(self, game: str) -> list[dict]:
        with closing(sqlite3.connect(self.database)) as db:
            rows = db.execute("SELECT manifest FROM points WHERE game=?", (game,))
            return sorted((json.loads(row[0]) for row in rows), key=lambda p: (p["created_utc"], p["id"]), reverse=True)

    @staticmethod
    def _get(db: sqlite3.Connection, identifier: str) -> dict:
        row = db.execute("SELECT manifest FROM points WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise StoreError("Restore point was not found.")
        point = json.loads(row[0])
        _validate_point(point)
        return point

    @staticmethod
    def _put(db: sqlite3.Connection, point: dict) -> None:
        _validate_point(point)
        payload = canonical_bytes(point).decode("ascii")
        existing = db.execute("SELECT manifest FROM points WHERE id=?", (point["id"],)).fetchone()
        if existing and existing[0] != payload:
            raise StoreError("An existing restore point has the same ID and different contents.")
        db.execute("INSERT OR IGNORE INTO points VALUES (?,?,?)", (point["id"], point["game"], payload))

    def capture(self, game: str, source: Path, edition_lock: dict | str, *, closed: bool,
                channel: str = "lab", campaign: str = "Original", parent: str | None = None) -> dict:
        if not closed:
            raise StoreError("Close the game before capturing a restore point.")
        source = plain_path(source)
        if source.is_relative_to(self.directory) or self.directory.is_relative_to(source):
            raise StoreError("Select the runtime save directory outside the snapshot store.")
        managed = next((name for name in ("play", "lab")
                        if source.is_relative_to(self.private / name / "runtimes")), None)
        guard_root = self.private
        edition_runs = self.private / "lab/runs"
        if source.is_relative_to(edition_runs):
            layout = source.relative_to(edition_runs).parts
            if len(layout) >= 3 and re.fullmatch(r"[0-9a-f]{16}", layout[0]) and layout[1:3] == ("lab", "runtimes"):
                guard_root = edition_runs / layout[0]
                managed = "lab"
        guard = nullcontext()
        if managed:
            if channel != managed:
                raise StoreError("The selected save folder belongs to the other runtime channel.")
            try:
                from .runtime_setup import reserve_idle_channel
            except ImportError:
                from runtime_setup import reserve_idle_channel
            guard = reserve_idle_channel(guard_root, managed)
        with guard:
            return self._capture(game, source, edition_lock, channel, campaign, parent, bool(managed))

    def _capture(self, game: str, source: Path, edition_lock: dict | str, channel: str,
                 campaign: str, parent: str | None, managed: bool) -> dict:
        paths = _files(source)
        point = {"schema_version": 1, "id": uuid.uuid4().hex, "game": game, "channel": channel,
                 "campaign": campaign, "parent": parent, "edition_lock": _lock_id(edition_lock),
                 "created_utc": datetime.now(timezone.utc).isoformat(),
                 "consistency": ("managed channel idle and reserved, " if managed else "")
                                + "closed by operator, files verified twice", "files": []}
        with self._transaction() as db:
            if parent:
                previous = self._get(db, parent)
                if previous["game"] != game:
                    raise StoreError("Parent restore point belongs to another game.")
            for path in paths:
                with path.open("rb") as stream:
                    data = stream.read(MAX_FILE + 1)
                if not 0 < len(data) <= MAX_FILE:
                    raise StoreError("Save file changed size during capture.")
                digest = _sha(data)
                point["files"].append({"path": member_path(path.relative_to(source).as_posix()),
                                       "kind": _kind(path), "bytes": len(data), "sha256": digest})
                db.execute("INSERT OR IGNORE INTO content VALUES (?,?)", (digest, data))
            if paths != _files(source):
                raise StoreError("The set of save files changed during capture.")
            for path, record in zip(paths, point["files"]):
                with path.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != record["sha256"]:
                        raise StoreError("A save file changed during capture.")
            self._put(db, point)
        return point

    def capture_cards(self, game: str, paths: dict[int, Path], edition_lock: dict,
                      channel: str, route: str, *, parent: str | None = None) -> dict | None:
        """Capture a closed, identified campaign's memory cards in port order."""
        from .managed_cards import read_cards

        cards = read_cards(game, paths)
        if not cards.title:
            return None
        files = [{"path": f"slot-{slot}.mcd", "kind": "card",
                  "bytes": len(body), "sha256": _sha(body)}
                 for slot, body in cards.slots.items()]
        with self._transaction() as db:
            row = db.execute(
                """SELECT manifest FROM points WHERE game=?
                   AND json_extract(manifest, '$.channel')=?
                   AND json_extract(manifest, '$.route')=?
                   ORDER BY json_extract(manifest, '$.created_utc') DESC, id DESC LIMIT 1""",
                (game, channel, route),
            ).fetchone()
            previous = json.loads(row[0]) if row else None
            if read_cards(game, paths) != cards:
                raise StoreError("A memory card changed during automatic backup.")
            if previous and previous["files"] == files:
                return None
            if parent and self._get(db, parent)["game"] != game:
                raise StoreError("Parent restore point belongs to another game.")
            point = {
                "schema_version": 1, "id": uuid.uuid4().hex, "game": game, "channel": channel,
                "campaign": ("Checkpoint session" if route.startswith("checkpoint/") else
                             "Restored campaign" if route.startswith("restored/") else "Original"),
                "route": route, "save_title": cards.title,
                "parent": previous["id"] if previous else parent,
                "edition_lock": _lock_id(edition_lock),
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "consistency": "closed managed runtime, memory cards verified twice", "files": files,
            }
            for file, body in zip(files, cards.slots.values(), strict=True):
                db.execute("INSERT OR IGNORE INTO content VALUES (?,?)", (file["sha256"], body))
            self._put(db, point)
        return point

    @staticmethod
    def _body(db: sqlite3.Connection, file: dict) -> bytes:
        row = db.execute("SELECT body FROM content WHERE digest=?", (file["sha256"],)).fetchone()
        if row is None or len(row[0]) != file["bytes"] or _sha(row[0]) != file["sha256"]:
            raise StoreError("A snapshot file failed integrity verification.")
        return row[0]

    def restore_to_lab(self, point_id: str, active_lock: dict | str, *, cards_only: bool = False) -> dict:
        with closing(sqlite3.connect(self.database)) as db:
            point = self._get(db, point_id)
            matches = _lock_id(active_lock) == point["edition_lock"]
            files = [f for f in point["files"] if not cards_only or f["kind"] == "card"]
            if not files:
                raise StoreError("This restore point has no ordinary memory card.")
            if not matches and any(f["kind"] == "state" for f in files):
                raise StoreError("Runtime state requires its original edition lock. Select cards only.")
            base = plain_path(self.private / "lab" / "restored" / point["game"])
            base.mkdir(parents=True, exist_ok=True)
            branch = uuid.uuid4().hex
            final = base / branch
            with tempfile.TemporaryDirectory(dir=base, prefix=".restore-") as temp:
                stage = Path(temp) / "branch"
                stage.mkdir()
                for file in files:
                    dest = stage / file["path"]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(self._body(db, file))
                    with dest.open("rb") as stream:
                        if hashlib.file_digest(stream, "sha256").hexdigest() != file["sha256"]:
                            raise StoreError("Restored copy failed integrity verification.")
                receipt = {"id": branch, "parent": point_id, "game": point["game"], "channel": "lab",
                           "source_lock": point["edition_lock"], "active_lock": _lock_id(active_lock),
                           "cards_only": cards_only, "game_load_validated": False, "files": files}
                (stage / "branch.json").write_bytes(canonical_bytes(receipt))
                stage.rename(final)
        return {**receipt, "path": str(final)}

    def export_point(self, point_id: str, destination: Path) -> None:
        destination = plain_path(destination)
        if destination.exists():
            raise StoreError("Choose a new file for the private save transfer.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database)) as db, tempfile.TemporaryDirectory(dir=destination.parent) as temp:
            point = self._get(db, point_id)
            staged = Path(temp) / "transfer.zip"
            with zipfile.ZipFile(staged, "x", zipfile.ZIP_STORED) as archive:
                archive.writestr("manifest.json", canonical_bytes(point))
                for file in point["files"]:
                    archive.writestr("files/" + file["path"], self._body(db, file))
            # Publish the completed file without replacing a concurrent export.
            if os.name == "nt":
                staged.rename(destination)
            else:
                os.link(staged, destination)

    def import_point(self, source: Path) -> dict:
        source = plain_path(source)
        if source.stat().st_size > MAX_TOTAL + 2**20:
            raise StoreError("Transfer exceeds the size limit.")
        with zipfile.ZipFile(source) as archive, self._transaction() as db:
            entries = archive.infolist()
            if len(entries) > MAX_FILES + 1 or len(entries) != len({i.filename.casefold() for i in entries}):
                raise StoreError("Unexpected or duplicate transfer entries.")
            for info in entries:
                member_path(info.filename)
                if (stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)
                        or info.flag_bits & 1 or info.external_attr & 0x400):
                    raise StoreError("Transfer contains an unsupported member.")
            manifest = archive.getinfo("manifest.json")
            if manifest.file_size > 2**20:
                raise StoreError("Transfer manifest exceeds the size limit.")
            point = json.loads(archive.read(manifest))
            _validate_point(point)
            if set(archive.namelist()) != {"manifest.json", *("files/" + f["path"] for f in point["files"])}:
                raise StoreError("Transfer members do not match the manifest.")
            for file in point["files"]:
                entry = archive.getinfo("files/" + file["path"])
                if entry.file_size != file["bytes"]:
                    raise StoreError("Transfer size differs from its manifest.")
                with archive.open(entry) as stream:
                    body = stream.read(entry.file_size + 1)
                if len(body) != entry.file_size or _sha(body) != file["sha256"]:
                    raise StoreError("Transfer digest differs from its manifest.")
                db.execute("INSERT OR IGNORE INTO content VALUES (?,?)", (file["sha256"], body))
            self._put(db, point)
        return point


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, default=Path("private"))
    commands = parser.add_subparsers(dest="action", required=True)
    capture = commands.add_parser("capture")
    capture.add_argument("game", choices=("bof3", "bof4"))
    capture.add_argument("source", type=Path)
    capture.add_argument("--lock", required=True, help="Full edition lock SHA-256.")
    capture.add_argument("--confirm-closed", action="store_true")
    capture.add_argument("--channel", choices=("lab", "play"), default="lab")
    capture.add_argument("--campaign", default="Original")
    capture.add_argument("--parent")
    commands.add_parser("list").add_argument("game", choices=("bof3", "bof4"))
    restore = commands.add_parser("restore-to-lab")
    restore.add_argument("id")
    restore.add_argument("--lock", required=True)
    restore.add_argument("--cards-only", action="store_true")
    export = commands.add_parser("export-private")
    export.add_argument("id")
    export.add_argument("destination", type=Path)
    commands.add_parser("import-private").add_argument("source", type=Path)
    args = parser.parse_args()
    try:
        store = CampaignStore(args.private_root)
        if args.action == "capture":
            result = store.capture(args.game, args.source, args.lock, closed=args.confirm_closed,
                                   campaign=args.campaign, channel=args.channel, parent=args.parent)
        elif args.action == "list":
            result = store.history(args.game)
        elif args.action == "restore-to-lab":
            result = store.restore_to_lab(args.id, args.lock, cards_only=args.cards_only)
        elif args.action == "export-private":
            store.export_point(args.id, args.destination)
            result = {"exported": str(args.destination)}
        else:
            result = store.import_point(args.source)
        print(json.dumps(result, indent=2))
        return 0
    except (KeyError, TypeError, OSError, ValueError, RuntimeError, sqlite3.Error, zipfile.BadZipFile) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
