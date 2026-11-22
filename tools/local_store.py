"""Filesystem primitives for private, local Atelier stores."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import tempfile


class StoreError(ValueError):
    """An input or filesystem condition requires action before continuing."""


def plain_path(path: Path) -> Path:
    """Reject links/junctions, including a broken link in a selected path."""
    absolute = Path(os.path.abspath(path))
    for component in (*reversed(absolute.parents), absolute):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise StoreError(f"Choose a location without links or reparse points: {component.name}")
    return absolute


def member_path(name: str) -> str:
    """Validate portable archive/manifest names before creating any output."""
    if not name or "\\" in name or name.startswith("/") or PureWindowsPath(name).drive:
        raise StoreError("Expected a portable relative filename.")
    parts = name.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(f"{prefix}{n}" for prefix in ("COM", "LPT") for n in "123456789¹²³")
    for part in parts:
        if (not part or part in {".", ".."} or part.endswith((" ", "."))
                or part.split(".")[0].upper() in reserved
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part)):
            raise StoreError("Unsafe or ambiguous filename.")
    path = PurePosixPath(*parts)
    if len(parts) > 32 or len(name) > 480:
        raise StoreError("Filename exceeds the permitted depth or length.")
    return path.as_posix()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def atomic_bytes(path: Path, payload: bytes) -> None:
    path = plain_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".write-", delete=False) as temp:
        temporary = Path(temp.name)
    try:
        with temporary.open("wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
