"""Resolve versioned presentation packs and activate immutable local edition locks."""
from __future__ import annotations

import argparse
from contextlib import closing
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from jsonschema import Draft202012Validator

try:
    from .local_store import StoreError, canonical_bytes, fingerprint, plain_path
except ImportError:
    from local_store import StoreError, canonical_bytes, fingerprint, plain_path


SCALINGS = {"Nearest", "NearestInteger", "BilinearSmooth", "BilinearHybrid",
            "BilinearSharp", "BilinearInteger", "Lanczos"}
SHA = re.compile(r"[0-9a-f]{64}")
PACK_ID = re.compile(r"[a-z][a-z0-9.-]{0,100}")
CAPABILITY = "display.scaling"
PIN = "v0.1-12442"


@lru_cache(maxsize=1)
def _pack_validator() -> Draft202012Validator:
    schema = Path(__file__).resolve().parents[1] / "schemas/mod-manifest-v2.schema.json"
    return Draft202012Validator(json.loads(schema.read_bytes()))


def _checked_sha(value: object) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise StoreError("A full SHA-256 fingerprint is required.")
    return value


def _base(base: dict) -> None:
    if base.get("game") not in {"bof3", "bof4"}:
        raise StoreError("Unknown game.")
    for key in ("game_sha256", "firmware_sha256", "runtime_sha256", "settings_sha256"):
        _checked_sha(base.get(key))
    if base.get("backend") != "duckstation-external" or base.get("version") != PIN:
        raise StoreError("This Lab settings adapter requires the inspected DuckStation version.")
    if base.get("scaling") not in SCALINGS:
        raise StoreError("Unknown base display setting.")


def integer_pack(game: str, revision: str, initial_scaling: str) -> dict:
    """Author a real option change for an explicitly selected Lab baseline."""
    if initial_scaling not in SCALINGS or initial_scaling == "NearestInteger" or game not in {"bof3", "bof4"}:
        raise StoreError("Select a supported baseline that does not already use nearest integer scaling.")
    return {"schema_version": 2, "id": f"atelier.{game}.integer-scaling", "version": "1.0.0",
            "title": "Nearest integer scaling", "game": game, "status": "experimental",
            "classification": "presentation", "supported_game_fingerprints": [_checked_sha(revision)],
            "required_capabilities": [CAPABILITY], "dependencies": [], "conflicts": [],
            "save_impact": "session-only", "operations": [{"kind": "config-option", "target": "display.scaling",
            "option_value": "NearestInteger", "expected_input_sha256": fingerprint(initial_scaling),
            "expected_output_sha256": fingerprint("NearestInteger")}],
            "rights": {"author": "BoF Atelier", "basis": "Locally authored option selection",
                       "publication_status": "private-only"}}


def resolve(base: dict, packs: list[dict], edition: str = "personal") -> dict:
    _base(base)
    if edition not in {"original", "enhanced", "personal"} or (edition == "original" and packs):
        raise StoreError("Original requires an empty pack list.")
    if len(packs) > 64:
        raise StoreError("Edition exceeds the pack limit.")
    by_id = {}
    for pack in packs:
        if not isinstance(pack, dict) or pack.get("schema_version") != 2:
            raise StoreError("Version 1 and draft manifests are inspectable only. Author an exact-revision v2 pack.")
        error = next(_pack_validator().iter_errors(pack), None)
        if error:
            raise StoreError(f"Invalid pack at {error.json_path}: {error.message}")
        identifier = pack.get("id", "")
        if not isinstance(identifier, str) or not PACK_ID.fullmatch(identifier) or identifier in by_id:
            raise StoreError("Invalid or duplicate pack ID.")
        if pack.get("game") != base["game"] or base["game_sha256"] not in pack.get("supported_game_fingerprints", []):
            raise StoreError(f"{identifier} does not support this exact game revision.")
        if pack.get("status") not in {"tested", "experimental"} or pack.get("classification") != "presentation":
            raise StoreError("This adapter handles reviewed presentation operations only.")
        if edition == "enhanced" and pack["status"] != "tested":
            raise StoreError("Enhanced requires a tested composition.")
        if pack.get("save_impact") not in {"session-only", "state-compatibility"}:
            raise StoreError("This adapter has no migration or persistent-save writer.")
        if not pack.get("rights", {}).get("basis") or not pack.get("operations"):
            raise StoreError("Pack requires rights evidence and at least one operation.")
        if set(pack.get("required_capabilities", [])) != {CAPABILITY}:
            raise StoreError("Pack requires an unavailable or undeclared backend capability.")
        try:
            Version(pack["version"])
        except (KeyError, TypeError, InvalidVersion) as error:
            raise StoreError("Invalid pack version.") from error
        by_id[identifier] = pack
    ordered = []
    complete = set()
    visiting = set()

    def visit(identifier: str) -> None:
        if identifier in visiting:
            raise StoreError("Pack dependency cycle.")
        if identifier in complete:
            return
        visiting.add(identifier)
        pack = by_id[identifier]
        if set(pack.get("conflicts", [])) & by_id.keys():
            raise StoreError(f"Declared pack conflict for {identifier}.")
        for dep in pack.get("dependencies", []):
            needed = dep["id"]
            if needed not in by_id:
                raise StoreError(f"Missing dependency {needed}.")
            try:
                constraint = SpecifierSet(dep["version_constraint"])
            except (KeyError, InvalidSpecifier) as error:
                raise StoreError(f"Unsupported dependency constraint for {needed}.") from error
            if Version(by_id[needed]["version"]) not in constraint:
                raise StoreError(f"Incompatible version of {needed}.")
            visit(needed)
        visiting.remove(identifier)
        complete.add(identifier)
        ordered.append(pack)

    for identifier in sorted(by_id):
        visit(identifier)
    scaling = base["scaling"]
    claimed = set()
    for pack in ordered:
        for op in pack["operations"]:
            if op.get("kind") != "config-option" or op.get("target") not in {"display.scaling", "display.integer-scaling"}:
                raise StoreError("Unknown operation or resource. No command or file was executed.")
            if CAPABILITY in claimed:
                raise StoreError("Semantic conflict: two operations change the display scaler.")
            claimed.add(CAPABILITY)
            if op.get("expected_input_sha256") != fingerprint(scaling):
                raise StoreError("The current option differs from the pack precondition.")
            value = op.get("option_value")
            if op["target"] == "display.integer-scaling":
                if value is not True:
                    raise StoreError("Integer scaling requires an explicit true value.")
                value = "NearestInteger"
            if value not in SCALINGS or value == scaling or op.get("expected_output_sha256") != fingerprint(value):
                raise StoreError("Invalid, ineffective or unverified display change.")
            scaling = value
    return {"schema_version": 1, "edition": edition, "game": base["game"], "base": dict(base),
            "packs": [{"id": p["id"], "version": p["version"], "sha256": fingerprint(p)} for p in ordered],
            "settings": {CAPABILITY: scaling}, "channel": "lab", "gameplay_validated": False}


def _scaling(text: str, value: str | None = None) -> tuple[str, str]:
    """Read or alter exactly one INI option in a new local copy."""
    lines = text.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in text else "\n"
    section = ""
    display_start = None
    entry = None
    initial = "BilinearSmooth"
    for index, line in enumerate(lines):
        stripped = line.strip()
        match = re.fullmatch(r"\[([^]]+)\]", stripped)
        if match:
            section = match[1].casefold()
            if section == "display":
                if display_start is not None:
                    raise StoreError("Duplicate Display section requires review.")
                display_start = index
        elif section == "display" and "=" in line:
            name, current = line.split("=", 1)
            if name.strip().casefold() == "scaling":
                if entry is not None:
                    raise StoreError("Duplicate Scaling option requires review.")
                entry = index
                initial = current.strip()
    if initial not in SCALINGS:
        raise StoreError("Unrecognised display scaler in the source settings.")
    if value and value != initial:
        if entry is not None:
            lines[entry] = "Scaling = " + value + newline
        elif display_start is not None:
            if not lines[display_start].endswith(("\r", "\n")):
                lines[display_start] += newline
            lines.insert(display_start + 1, "Scaling = " + value + newline)
        else:
            lines.extend([newline, "[Display]" + newline, "Scaling = " + value + newline])
    return initial, "".join(lines)


class EditionStore:
    def __init__(self, private_root: Path):
        self.root = plain_path(private_root / "lab" / "editions")
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = plain_path(self.root / "editions.sqlite3")
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS locks (id TEXT PRIMARY KEY, body TEXT NOT NULL, settings_sha256 TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS active (game TEXT PRIMARY KEY, id TEXT NOT NULL, previous TEXT)")

    def activate(self, base: dict, packs: list[dict], source_settings: bytes, edition: str) -> dict:
        if len(source_settings) > 4 * 1024**2 or hashlib.sha256(source_settings).hexdigest() != base["settings_sha256"]:
            raise StoreError("Base runtime settings changed.")
        lock = resolve(base, packs, edition)
        initial, text = _scaling(source_settings.decode("utf-8-sig"), lock["settings"][CAPABILITY])
        if initial != base["scaling"]:
            raise StoreError("The recorded display baseline differs from the runtime configuration.")
        content = source_settings if not packs else text.encode("utf-8-sig" if source_settings.startswith(b"\xef\xbb\xbf") else "utf-8")
        identifier = fingerprint(lock)
        final = plain_path(self.root / identifier)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            receipt = canonical_bytes(lock)
            if not final.exists():
                with tempfile.TemporaryDirectory(dir=self.root, prefix=".edition-") as temp:
                    stage = Path(temp) / "resolved"
                    stage.mkdir()
                    (stage / "settings.ini").write_bytes(content)
                    (stage / "edition-lock.json").write_bytes(receipt)
                    stage.rename(final)
            if (plain_path(final / "settings.ini").read_bytes() != content
                    or plain_path(final / "edition-lock.json").read_bytes() != receipt):
                raise StoreError("Existing edition failed verification. Previous selection was retained.")
            db.execute("INSERT OR IGNORE INTO locks VALUES (?,?,?)",
                       (identifier, receipt.decode("ascii"), hashlib.sha256(content).hexdigest()))
            old = db.execute("SELECT id FROM active WHERE game=?", (base["game"],)).fetchone()
            if not old or old[0] != identifier:
                db.execute("INSERT OR REPLACE INTO active VALUES (?,?,?)",
                           (base["game"], identifier, old[0] if old else None))
        return {"id": identifier, "path": str(final), "lock": lock}

    def rollback(self, game: str) -> str:
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id,previous FROM active WHERE game=?", (game,)).fetchone()
            if not row or not row[1]:
                raise StoreError("No previous edition exists for this game.")
            previous = row[1]
            expected = db.execute("SELECT body,settings_sha256 FROM locks WHERE id=?", (previous,)).fetchone()
            if not expected or not SHA.fullmatch(previous):
                raise StoreError("Previous lock record is missing.")
            if (plain_path(self.root / previous / "edition-lock.json").read_bytes() != expected[0].encode("ascii")
                    or hashlib.sha256(plain_path(self.root / previous / "settings.ini").read_bytes()).hexdigest() != expected[1]):
                raise StoreError("Previous edition failed verification.")
            db.execute("UPDATE active SET id=?,previous=? WHERE game=?", (previous, row[0], game))
        return previous


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, default=Path("private"))
    subs = parser.add_subparsers(dest="action", required=True)
    p = subs.add_parser("activate-lab")
    p.add_argument("base", type=Path)
    p.add_argument("settings", type=Path)
    p.add_argument("--edition", choices=("original", "enhanced", "personal"), required=True)
    p.add_argument("--pack", action="append", default=[], type=Path)
    p = subs.add_parser("rollback-lab")
    p.add_argument("game", choices=("bof3", "bof4"))
    args = parser.parse_args()
    try:
        store = EditionStore(args.private_root)
        if args.action == "rollback-lab":
            result = {"restored_lock": store.rollback(args.game)}
        else:
            base = json.loads(args.base.read_bytes())
            packs = [json.loads(p.read_bytes()) for p in args.pack]
            result = store.activate(base, packs, args.settings.read_bytes(), args.edition)
        print(json.dumps(result, indent=2))
        return 0
    except (KeyError, TypeError, ValueError, OSError, sqlite3.Error) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
