"""Private, version-pinned stock runtime setup. Game and firmware files stay local."""

from __future__ import annotations

import argparse
import configparser
import contextlib
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
from functools import lru_cache, partial
from typing import Any
import zipfile

try:
    from . import bofkit, local_store
except ImportError:  # A developer may also run python tools/runtime_setup.py.
    import bofkit
    import local_store


ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "research/dependency-catalogue.json"
DEFAULT_PRIVATE = ROOT / "private"
EXECUTABLE_SUFFIXES = {
    ".exe",
    ".dll",
    ".com",
    ".scr",
    ".ocx",
    ".pyd",
    ".py",
    ".ps1",
    ".bat",
    ".cmd",
    ".lua",
}


class RuntimeSetupError(RuntimeError):
    """The chosen installation or play action cannot proceed safely."""


@lru_cache(maxsize=1)
def _catalogue() -> dict[str, dict[str, Any]]:
    entries = json.loads(CATALOGUE.read_text(encoding="utf-8"))["components"]
    return {entry["id"]: entry for entry in entries}


def _path(root: Path, *parts: str) -> Path:
    root = Path(root).absolute()
    target = root.joinpath(*parts)
    if not target.is_relative_to(root) or ".." in target.parts:
        raise RuntimeSetupError("Path leaves the selected private storage.")
    try:
        return local_store.plain_path(target)
    except local_store.StoreError as error:
        raise RuntimeSetupError(str(error)) from error


def _component(backend: str, channel: str) -> dict[str, Any]:
    if channel not in ("lab", "play") or backend not in (
        "duckstation",
        "pcsx-redux",
        "pcsx-redux-cli",
    ):
        raise RuntimeSetupError("Unknown runtime or channel.")
    if backend.startswith("pcsx-redux") and channel != "lab":
        raise RuntimeSetupError("PCSX-Redux is qualified for research use only.")
    return _catalogue()[backend + "-windows-x64"]


def _installation(root: Path, channel: str, backend: str) -> Path:
    entry = _component(backend, channel)
    return _path(root, channel, "runtimes", backend, entry["version"])


def _archive(root: Path, backend: str, entry: dict[str, Any]) -> Path:
    package = entry["package"]
    name = package["url"].rsplit("/", 1)[-1]
    folder = _path(root, "downloads", backend, str(package["release_id"]))
    atomically_published = _path(folder, name + ".asset", name)
    if atomically_published.is_file():
        return atomically_published
    return _path(folder, name)


def _check_windows() -> None:
    if os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeSetupError(
            "This qualified runtime package requires 64-bit Windows on x86-64."
        )


def _digest(path: Path, algorithm: str = "sha256") -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


@lru_cache(maxsize=512)
def _cached_digest(path: Path, mtime_ns: int, ctime_ns: int, size: int) -> str:
    return _digest(path)


def _matches(path: Path, expected: str) -> bool:
    if not path.is_file():
        return False
    info = path.stat()
    return (
        _cached_digest(path, info.st_mtime_ns, info.st_ctime_ns, info.st_size)
        == expected
    )


def _atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=".receipt-", delete=False, encoding="utf-8"
    ) as output:
        temporary = Path(output.name)
        try:
            json.dump(data, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            output.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _zip_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > 4000 or sum(entry.file_size for entry in entries) > 1024**3:
        raise RuntimeSetupError("Runtime archive exceeds the installation limits.")
    seen: set[str] = set()
    files: set[str] = set()
    directories: set[str] = set()
    for entry in entries:
        name = entry.filename.rstrip("/")
        mode = entry.external_attr >> 16
        try:
            key = local_store.member_path(name).casefold()
        except local_store.StoreError as error:
            raise RuntimeSetupError(
                "Runtime archive contains an unsafe entry."
            ) from error
        parents = {
            str(parent).replace("\\", "/")
            for parent in Path(key).parents
            if str(parent) != "."
        }
        if (
            entry.flag_bits & 1
            or (entry.external_attr & 0x400)
            or parents & files
            or stat.S_IFMT(mode) not in (0, stat.S_IFDIR, stat.S_IFREG)
            or key in seen
            or (not entry.is_dir() and key in directories)
        ):
            raise RuntimeSetupError(
                "Runtime archive contains an unsafe or duplicate entry."
            )
        seen.add(key)
        directories.update(parents)
        (directories if entry.is_dir() else files).add(key)
    return entries


def _verify_download(path: Path, entry: dict[str, Any]) -> None:
    package = entry["package"]
    if not path.is_file():
        raise RuntimeSetupError(
            "The pinned official package is absent from private downloads."
        )
    if path.stat().st_size != package["bytes"] or not _matches(path, package["sha256"]):
        raise RuntimeSetupError(
            "The private runtime package differs from the pinned release."
        )
    if (
        package.get("publisher_sha3_256")
        and _digest(path, "sha3_256") != package["publisher_sha3_256"]
    ):
        raise RuntimeSetupError(
            "The runtime package differs from the publisher's SHA3-256."
        )


def import_runtime_package(
    private_root: Path, source: Path, channel: str = "lab", backend: str = "duckstation"
) -> dict:
    """Install the user's selected, exact official ZIP without executing an installer."""
    _check_windows()
    entry = _component(backend, channel)
    _cache_package(private_root, source, backend, entry)
    return prepare_runtime(private_root, channel, backend)


def _cache_package(private_root: Path, source: Path, backend: str, entry: dict) -> Path:
    selected = local_store.plain_path(Path(source))
    _verify_download(selected, entry)
    cache = _archive(private_root, backend, entry)
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists():
        if (
            shutil.disk_usage(cache.parent).free
            < entry["package"]["bytes"] + 16 * 1024**2
        ):
            raise RuntimeSetupError(
                "Insufficient free space to store the selected package."
            )
        with tempfile.NamedTemporaryFile(
            dir=cache.parent, prefix=".package-", delete=False
        ) as output:
            temporary = Path(output.name)
        try:
            with selected.open("rb") as original, temporary.open("wb") as output:
                remaining = entry["package"]["bytes"]
                while remaining:
                    piece = original.read(min(1024**2, remaining))
                    if not piece:
                        raise RuntimeSetupError(
                            "The selected package changed while copying."
                        )
                    output.write(piece)
                    remaining -= len(piece)
                if original.read(1):
                    raise RuntimeSetupError(
                        "The selected package changed while copying."
                    )
                output.flush()
                os.fsync(output.fileno())
            _verify_download(temporary, entry)
            try:
                if os.name == "nt":
                    temporary.rename(
                        cache
                    )  # Windows refuses to replace an existing destination.
                else:
                    os.link(temporary, cache)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    _verify_download(cache, entry)
    return cache


def prepare_runtime(
    private_root: Path, channel: str = "lab", backend: str = "duckstation"
) -> dict:
    """Install a verified archive beside other versions. Existing settings and saves are retained."""
    _check_windows()
    with reserve_idle_channel(private_root, channel):
        return _prepare_runtime(private_root, channel, backend)


def _prepare_runtime(private_root: Path, channel: str, backend: str) -> dict:
    _check_windows()
    entry = _component(backend, channel)
    destination = _installation(private_root, channel, backend)
    package = _archive(private_root, backend, entry)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        _verify_installation(private_root, channel, backend)
        return _installation_info(private_root, channel, backend)
    _verify_download(package, entry)
    # Build a new tree on the destination volume. Keep private configuration out of the ZIP.
    with tempfile.TemporaryDirectory(
        prefix=".stage-", dir=destination.parent
    ) as workspace:
        staging = Path(workspace) / "payload"
        _write_stock_tree(staging, package, entry, channel, backend)
        try:
            staging.rename(destination)
        except OSError:
            if not destination.exists():
                raise
            _verify_installation(private_root, channel, backend)
    return _installation_info(private_root, channel, backend)


def _write_stock_tree(
    staging: Path, package: Path, entry: dict, channel: str, backend: str
) -> None:
    staging.mkdir()
    immutable: dict[str, str] = {}
    with zipfile.ZipFile(package) as archive:
        entries = _zip_entries(archive)
        if (
            shutil.disk_usage(staging).free
            < sum(item.file_size for item in entries) + 16 * 1024**2
        ):
            raise RuntimeSetupError("Insufficient free space for the verified runtime.")
        for item in entries:
            target = staging.joinpath(*item.filename.rstrip("/").split("/"))
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            immutable[item.filename] = _digest(target)
    executable = entry["package"]["executable"]
    if (
        _manifest_digest(immutable) != entry["package"]["files_sha256"]
        or immutable.get(executable) != entry["package"]["executable_sha256"]
    ):
        raise RuntimeSetupError(
            "The expected runtime executable is missing or differs."
        )
    if backend == "duckstation":
        (staging / "portable.txt").touch(exist_ok=False)
    else:
        embedded = json.loads((staging / "version.json").read_text(encoding="utf-8"))
        if (
            embedded.get("changeset") != entry["package"]["source_commit"]
            or embedded.get("buildId") != entry["package"]["release_id"]
        ):
            raise RuntimeSetupError(
                "Embedded PCSX-Redux identity differs from the official package record."
            )
        if (
            immutable.get("openbios.bin")
            != _catalogue()["openbios-psx-rom"]["member"]["sha256"]
        ):
            raise RuntimeSetupError(
                "Bundled firmware differs from the verified firmware member."
            )
    _atomic_json(
        staging / ".atelier-runtime.json",
        {
            "version": entry["version"],
            "backend": backend,
            "channel": channel,
            "sha256": entry["package"]["sha256"],
            "files": immutable,
        },
    )


def _installation_info(root: Path, channel: str, backend: str) -> dict:
    entry = _component(backend, channel)
    location = _installation(root, channel, backend)
    return {
        "backend": backend,
        "version": entry["version"],
        "channel": channel,
        "executable": str(location / entry["package"]["executable"]),
        "data_root": str(location),
    }


def _verify_installation(root: Path, channel: str, backend: str) -> None:
    entry = _component(backend, channel)
    directory = _installation(root, channel, backend)
    _verify_tree(directory, entry, channel, backend)


def _verify_tree(directory: Path, entry: dict, channel: str, backend: str) -> None:
    receipt = _path(directory, ".atelier-runtime.json")
    if not receipt.is_file():
        raise RuntimeSetupError("Prepare the private runtime for this channel.")
    if backend == "duckstation" and not _path(directory, "portable.txt").is_file():
        raise RuntimeSetupError("The isolated runtime's portable marker is missing.")
    try:
        manifest = json.loads(receipt.read_text(encoding="utf-8"))
        if (
            manifest["channel"] != channel
            or manifest["backend"] != backend
            or manifest["version"] != entry["version"]
            or manifest["sha256"] != entry["package"]["sha256"]
        ):
            raise RuntimeSetupError(
                "The local runtime receipt belongs to another installation."
            )
        expected_files = manifest["files"]
        if (
            not isinstance(expected_files, dict)
            or _manifest_digest(expected_files) != entry["package"]["files_sha256"]
        ):
            raise RuntimeSetupError(
                "The installed runtime manifest differs from the verified package."
            )
        for name, expected in expected_files.items():
            target = _path(directory, *name.split("/"))
            if not target.is_file() or _digest(target) != expected:
                raise RuntimeSetupError(
                    "A runtime component is missing or damaged: " + name
                )
        approved = {name.casefold() for name in expected_files}
        for parent, folders, files in os.walk(directory, followlinks=False):
            relative = Path(parent).relative_to(directory)
            for folder in folders:
                _path(directory, *relative.parts, folder)
            for name in files:
                if (
                    Path(name).suffix.casefold() in EXECUTABLE_SUFFIXES
                    and (relative / name).as_posix().casefold() not in approved
                ):
                    raise RuntimeSetupError(
                        "An unrecognised executable component requires a stock repair: "
                        + name
                    )
    except (KeyError, ValueError, OSError, zipfile.BadZipFile) as error:
        raise RuntimeSetupError("Unable to verify the private installation.") from error


def _manifest_digest(files: dict[str, str]) -> str:
    serialised = json.dumps(
        files, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def _recover_repair(directory: Path, record: Path) -> None:
    if not record.exists():
        return
    data = json.loads(record.read_text(encoding="utf-8"))
    token = data.get("transaction")
    if (
        not isinstance(token, str)
        or len(token) != 32
        or any(char not in "0123456789abcdef" for char in token)
    ):
        raise RuntimeSetupError("The private repair journal requires inspection.")
    backup = _path(directory.parent, f".repair-backup-{token}")
    if not directory.exists() and backup.is_dir():
        backup.rename(directory)
    if not directory.exists():
        raise RuntimeSetupError(
            "The previous repair has no recoverable installation. Its files were retained."
        )
    record.unlink()


def repair_runtime(
    private_root: Path, channel: str = "lab", backend: str = "duckstation"
) -> dict:
    """Rebuild stock binaries offline, copy closed private data, then swap the complete tree."""
    _check_windows()
    entry = _component(backend, channel)
    directory = _installation(private_root, channel, backend)
    journal = _path(directory.parent, ".repair.json")
    with reserve_idle_channel(private_root, channel):
        if backend.startswith("pcsx-redux"):
            for name in ("pcsx-redux.exe", "pcsx-redux.main"):
                if _matching_process(_path(directory, name)):
                    raise RuntimeSetupError(
                        "Close the Lab reference emulator before repair."
                    )
        _recover_repair(directory, journal)
        if not directory.exists():
            return _prepare_runtime(private_root, channel, backend)
        try:
            _verify_installation(private_root, channel, backend)
            return _installation_info(private_root, channel, backend) | {
                "repaired": False
            }
        except RuntimeSetupError:
            pass
        archive = _archive(private_root, backend, entry)
        _verify_download(archive, entry)
        token = uuid.uuid4().hex
        backup = _path(directory.parent, f".repair-backup-{token}")
        with tempfile.TemporaryDirectory(
            dir=directory.parent, prefix=".repair-stage-"
        ) as scratch:
            workspace = Path(scratch)
            fresh = workspace / "payload"
            _write_stock_tree(fresh, archive, entry, channel, backend)
            clean = json.loads(
                (fresh / ".atelier-runtime.json").read_text(encoding="utf-8")
            )
            immutable = {name.casefold() for name in clean["files"]} | {
                "portable.txt",
                ".atelier-runtime.json",
            }
            for parent, folders, names in os.walk(directory, followlinks=False):
                relative = Path(parent).relative_to(directory)
                for folder in folders:
                    _path(directory, *relative.parts, folder)
                    (fresh / relative / folder).mkdir(parents=True, exist_ok=True)
                for name in names:
                    old = _path(directory, *relative.parts, name)
                    if (relative / name).as_posix().casefold() in immutable:
                        continue
                    if old.suffix.casefold() in EXECUTABLE_SUFFIXES:
                        continue  # Preserve unfamiliar executable content only in the previous tree.
                    if not old.is_file():
                        raise RuntimeSetupError(
                            "A private profile entry could not be copied safely."
                        )
                    copied = fresh / relative / name
                    shutil.copy2(old, copied)
                    if _digest(old) != _digest(copied):
                        raise RuntimeSetupError(
                            "A private file changed during repair. Close the application and retry."
                        )
            _verify_tree(fresh, entry, channel, backend)
            _atomic_json(journal, {"transaction": token})
            directory.rename(backup)
            try:
                fresh.rename(directory)
            except BaseException:
                _recover_repair(directory, journal)
                raise
            _recover_repair(directory, journal)
        return _installation_info(private_root, channel, backend) | {
            "repaired": True,
            "previous_installation": str(backup),
        }


def _binding(root: Path, channel: str) -> Path:
    _component("duckstation", channel)
    return _path(root, channel, "firmware-selection.json")


def _bind(root: Path, channel: str, data: dict) -> dict:
    with reserve_idle_channel(root, channel):
        return _bind_idle(root, channel, data)


def _bind_idle(root: Path, channel: str, data: dict) -> dict:
    _verify_installation(root, channel, "duckstation")
    directory = _installation(root, channel, "duckstation")
    if not _path(directory, "portable.txt").is_file():
        raise RuntimeSetupError(
            "Prepare the channel's isolated DuckStation runtime first."
        )
    if channel == "play" and (
        data["evidence"] != "upstream-retail-fingerprint" or data["region"] != "NTSC-U"
    ):
        raise RuntimeSetupError(
            "Stable Play currently requires a recognised North American retail firmware file."
        )
    source = Path(data["path"])
    if not _matches(source, data["sha256"]):
        raise RuntimeSetupError(
            "The selected firmware changed before it could be placed."
        )
    bios_dir = _path(directory, "bios")
    bios_dir.mkdir(exist_ok=True)
    name = "atelier-" + data["sha256"] + ".bin"
    target = _path(bios_dir, name)
    if target.exists() and not _matches(target, data["sha256"]):
        raise RuntimeSetupError(
            "The existing selected firmware file differs. Keep it for inspection."
        )
    if not target.exists():
        with tempfile.NamedTemporaryFile(dir=bios_dir, delete=False) as out:
            temporary = Path(out.name)
            try:
                with source.open("rb") as original:
                    shutil.copyfileobj(original, out)
            except BaseException:
                out.close()
                temporary.unlink(missing_ok=True)
                raise
        try:
            if not _matches(temporary, data["sha256"]):
                raise RuntimeSetupError("Firmware failed its copy verification.")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    _select_stock_firmware(directory, name)
    _atomic_json(
        _binding(root, channel),
        {k: data[k] for k in ("name", "region", "sha256", "evidence")}
        | {"filename": name},
    )
    return {
        "firmware": data["name"],
        "channel": channel,
        "sha256": data["sha256"],
        "path": str(target),
    }


def import_firmware(
    private_root: Path, source: Path, channel: str = "play", member: str | None = None
) -> dict:
    try:
        from .firmware import import_firmware as recognise
    except ImportError:
        from firmware import import_firmware as recognise
    receipt = recognise(source, private_root, member=member)
    if receipt["evidence"] == "openbios-marker-only":
        raise RuntimeSetupError(
            "This OpenBIOS file has not been qualified for gameplay. Use the verified Lab replacement."
        )
    return _bind(private_root, channel, receipt)


def use_lab_openbios(private_root: Path) -> dict:
    firmware = _catalogue()["openbios-psx-rom"]["member"]
    backend = "pcsx-redux-cli"
    if not _installation(private_root, "lab", backend).exists():
        backend = "pcsx-redux"
    _verify_installation(private_root, "lab", backend)
    source = _path(_installation(private_root, "lab", backend), firmware["name"])
    build = _component(backend, "lab")["package"]["release_id"]
    return _bind(
        private_root,
        "lab",
        {
            "name": f"OpenBIOS from Redux build {build}",
            "region": "Auto",
            "sha256": firmware["sha256"],
            "evidence": "official-package-member",
            "path": str(source),
        },
    )


def _hidden() -> dict:
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return {"startupinfo": startup, "creationflags": subprocess.CREATE_NO_WINDOW}


def _rewrite_settings(path: Path, changes: dict[str, dict[str, str | list[str]]]) -> None:
    """Update only nominated keys, preserving repeated controller bindings and other settings."""
    lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    pending = {section: dict(values) for section, values in changes.items()}
    result: list[str] = []
    section = ""
    seen_sections: set[str] = set()

    def entries(key, value):
        return [f"{key} = {item}\n" for item in (value if isinstance(value, list) else [value])]

    def finish() -> None:
        for key, value in pending.get(section, {}).items():
            result.extend(entries(key, value))
        pending.pop(section, None)

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            finish()
            section = stripped[1:-1]
            if section in changes and section in seen_sections:
                raise RuntimeSetupError("A managed settings section occurs twice.")
            seen_sections.add(section)
        elif "=" in stripped and not stripped.startswith(("#", ";")):
            key = stripped.split("=", 1)[0].strip()
            if key in changes.get(section, {}):
                if key in pending.get(section, {}):
                    result.extend(entries(key, pending[section].pop(key)))
                continue
        result.append(line if line.endswith(("\n", "\r")) else line + "\n")
    finish()
    for missing, values in pending.items():
        result.append(f"\n[{missing}]\n")
        for key, value in values.items():
            result.extend(entries(key, value))
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        prefix=".settings-",
        delete=False,
        encoding="utf-8",
        newline="",
    ) as output:
        temporary = Path(output.name)
        try:
            output.writelines(result)
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            output.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _select_stock_firmware(directory: Path, filename: str) -> None:
    settings = _path(directory, "settings.ini")
    if not settings.exists():
        # Ask the pristine stock binary to initialise its own defaults. The offscreen
        # wizard has no game, memory card or live session attached.
        executable = (
            directory / _component("duckstation", "lab")["package"]["executable"]
        )
        with subprocess.Popen(
            [str(executable), "-setupwizard"],
            cwd=directory,
            env=os.environ | {"QT_QPA_PLATFORM": "offscreen"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_hidden(),
        ) as process:
            try:
                for _ in range(80):
                    if settings.is_file() and settings.stat().st_size > 0:
                        break
                    if process.poll() is not None:
                        break
                    time.sleep(0.1)
            finally:
                if process.poll() is None:
                    process.terminate()
        if not settings.is_file() or not settings.stat().st_size:
            raise RuntimeSetupError(
                "The stock runtime could not initialise defaults in its portable folder."
            )
    _rewrite_settings(
        settings,
        {
            "BIOS": {
                "PathNTSCU": filename,
                "SearchDirectory": "bios",
                "PatchFastBoot": "false",
            },
            "Main": {"SetupWizardIncomplete": "false"},
            "AutoUpdater": {"CheckAtStartup": "false"},
        },
    )


def _review_paths(directory: Path, settings: configparser.ConfigParser) -> None:
    # The upstream backend accepts absolute save paths, including overrides from
    # older profiles. Reject these before starting either private channel.
    paths = [
        ("BIOS", "SearchDirectory", "bios"),
        ("MemoryCards", "Directory", "memcards"),
        *(("MemoryCards", f"Card{slot}Path", "") for slot in range(1, 9)),
    ]
    if settings.has_section("Folders"):
        paths.extend(("Folders", name, "") for name in settings.options("Folders"))
    for section, key, default in paths:
        selected = settings.get(section, key, fallback=default)
        if selected:
            pure = PureWindowsPath(selected)
            if pure.drive or pure.root or ".." in pure.parts or ":" in selected:
                raise RuntimeSetupError(
                    "An isolated runtime folder points outside this channel. Review local settings."
                )
            _path(directory, *pure.parts)


def _effective_game_settings(directory: Path, game: str) -> configparser.ConfigParser:
    settings = configparser.ConfigParser(strict=False, interpolation=None)
    settings.read_string(
        _path(directory, "settings.ini").read_text(encoding="utf-8-sig")
    )
    folder = PureWindowsPath(
        settings.get("Folders", "GameSettings", fallback="gamesettings")
    )
    serial = {"bof3": "SLUS-00422", "bof4": "SLUS-01324"}[game]
    override = _path(directory, *folder.parts, serial + ".ini")
    if override.exists() and settings.getboolean("Main", "ApplyGameSettings", fallback=True):
        settings.read_string(override.read_text(encoding="utf-8-sig"))
    _review_paths(directory, settings)
    return settings


def _review_game_settings(directory: Path, game: str, firmware: str) -> None:
    settings = _effective_game_settings(directory, game)
    if (
        settings.get("BIOS", "PathNTSCU", fallback="") != firmware
        or settings.get("BIOS", "SearchDirectory", fallback="bios") != "bios"
    ):
        raise RuntimeSetupError(
            "The game's firmware override differs from the selected private firmware."
        )
    for section, key, default in (
        ("MemoryCards", "Directory", "memcards"),
        ("Folders", "SaveStates", "savestates"),
    ):
        relative = PureWindowsPath(settings.get(section, key, fallback=default))
        target = _path(directory, *relative.parts)
        for parent, folders, files in os.walk(target, followlinks=False):
            for name in (*folders, *files):
                _path(Path(parent), name)


def _selected_firmware(root: Path, channel: str, directory: Path) -> dict:
    binding = _binding(root, channel)
    if not binding.is_file():
        raise RuntimeSetupError(
            "Choose a recognised North American BIOS or use the replacement firmware in Lab."
        )
    try:
        data = json.loads(binding.read_text(encoding="utf-8"))
        digest = data["sha256"]
        filename = data["filename"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or filename != "atelier-" + digest + ".bin"
        ):
            raise RuntimeSetupError("The firmware binding is invalid.")
        target = _path(directory, "bios", filename)
        if not _matches(target, digest):
            raise RuntimeSetupError("The selected firmware is missing or damaged.")
        if data["evidence"] == "official-package-member":
            if (
                channel != "lab"
                or digest != _catalogue()["openbios-psx-rom"]["member"]["sha256"]
            ):
                raise RuntimeSetupError(
                    "This replacement firmware is available in Lab only."
                )
        elif (
            data["evidence"] == "upstream-retail-fingerprint"
            and data["region"] == "NTSC-U"
        ):
            # Reuse the independently maintained identification table, rather than
            # trusting user-editable metadata to classify a private firmware file.
            try:
                from . import firmware
            except ImportError:
                import firmware
            record = firmware.inspect_firmware(target)
            if (
                record["evidence"] != "upstream-retail-fingerprint"
                or record["region"] != "NTSC-U"
            ):
                raise RuntimeSetupError(
                    "The selected firmware identification does not match its binding."
                )
        else:
            raise RuntimeSetupError("The firmware is unsupported for this channel.")
        config = configparser.ConfigParser(strict=False, interpolation=None)
        config.read_string(
            _path(directory, "settings.ini").read_text(encoding="utf-8-sig")
        )
        _review_paths(directory, config)
        if (
            config.get("BIOS", "PathNTSCU", fallback="") != filename
            or config.get("BIOS", "SearchDirectory", fallback="bios") != "bios"
        ):
            raise RuntimeSetupError(
                "Stock runtime BIOS selection has changed. Select the firmware again."
            )
        return data
    except (ValueError, KeyError, OSError, configparser.Error) as error:
        raise RuntimeSetupError(
            "The private firmware selection needs repair."
        ) from error


def _process_identity(pid: int) -> tuple[str, int] | None:
    if os.name != "nt" or pid <= 0:
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        *(ctypes.POINTER(wintypes.FILETIME),) * 4,
    )
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        if (
            not kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            or code.value != 259
        ):
            return None
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        created, ended, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        if not kernel.GetProcessTimes(
            handle, *map(ctypes.byref, (created, ended, kernel_time, user_time))
        ):
            return None
        return os.path.normcase(buffer.value), (
            created.dwHighDateTime << 32
        ) | created.dwLowDateTime
    finally:
        kernel.CloseHandle(handle)


def _matching_process(executable: Path) -> bool:
    """Find independently opened copies of this one exact managed executable."""
    if os.name != "nt" or not executable.is_file():
        return False

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("pid", wintypes.DWORD),
            ("defaultHeap", ctypes.c_size_t),
            ("module", wintypes.DWORD),
            ("threads", wintypes.DWORD),
            ("parent", wintypes.DWORD),
            ("priority", wintypes.LONG),
            ("flags", wintypes.DWORD),
            ("name", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.Process32NextW.argtypes = kernel.Process32FirstW.argtypes
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise RuntimeSetupError(
            "Windows could not check whether this game channel is busy."
        )
    expected = os.path.normcase(str(executable))
    try:
        record = ProcessEntry()
        record.dwSize = ctypes.sizeof(record)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(record))
        while found:
            if record.name.casefold() == executable.name.casefold():
                observed = _process_identity(record.pid)
                if observed and observed[0] == expected:
                    return True
            found = kernel.Process32NextW(snapshot, ctypes.byref(record))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise RuntimeSetupError(
                "Windows did not finish checking the active game channel."
            )
        return False
    finally:
        kernel.CloseHandle(snapshot)


def _is_active(root: Path, channel: str) -> bool:
    marker = _path(root, channel, "active-game.json")
    if marker.is_file():
        try:
            saved = json.loads(marker.read_text(encoding="utf-8"))
            identity = _process_identity(int(saved["pid"]))
            if identity is not None and identity == (
                os.path.normcase(saved["executable"]),
                saved["created"],
            ):
                return True
        except (OSError, TypeError, ValueError, KeyError) as error:
            raise RuntimeSetupError(
                "The managed session record is unreadable. Check the runtime before continuing."
            ) from error
    executable = (
        _installation(root, channel, "duckstation")
        / _component("duckstation", channel)["package"]["executable"]
    )
    return _matching_process(executable)


def runtime_status(private_root: Path, channel: str = "play") -> dict:
    result = _installation_info(private_root, channel, "duckstation")
    result.update(
        runtime_ready=False,
        firmware_ready=False,
        can_launch=False,
        running=False,
        reason="",
    )
    directory = _installation(private_root, channel, "duckstation")
    try:
        _check_windows()
        result["running"] = _is_active(private_root, channel)
        # This is an inexpensive availability probe. Launch also verifies the entire
        # installed package, including DLLs and resources, against the official archive.
        if not (
            _path(directory, "portable.txt").is_file()
            and _path(directory, ".atelier-runtime.json").is_file()
            and _matches(
                _path(directory, Path(result["executable"]).name),
                _component("duckstation", channel)["package"]["executable_sha256"],
            )
        ):
            raise RuntimeSetupError("Prepare the pinned private Windows runtime.")
        result["runtime_ready"] = True
        data = _selected_firmware(private_root, channel, directory)
        result.update(
            firmware_ready=True,
            firmware=data["name"],
            firmware_sha256=data["sha256"],
            firmware_evidence=data["evidence"],
            can_launch=not result["running"],
        )
        result["reason"] = (
            "A game is already running in this channel."
            if result["running"]
            else "Ready"
        )
    except (RuntimeSetupError, OSError) as error:
        result["reason"] = str(error)
    return result


def _verified_cue(root: Path, game: str, cue: Path) -> Path:
    records = {entry["game"]: entry for entry in bofkit.load_inventory(ROOT)}
    if game not in records:
        raise RuntimeSetupError("Select one of the two supported game revisions.")
    candidate = Path(cue).absolute()
    game_root = _path(root, "games", game)
    if not candidate.is_relative_to(game_root):
        raise RuntimeSetupError(
            "The launch descriptor is outside the verified game library."
        )
    candidate = _path(game_root, *candidate.relative_to(game_root).parts)
    record = records[game]
    if not _matches(candidate, record["working_cue"]["sha256"]):
        raise RuntimeSetupError(
            "The launch descriptor differs from the verified revision."
        )
    try:
        layout = bofkit.parse_cue(candidate)
        tracks = {
            Path(entry["name"]).name: entry
            for entry in record["entries"]
            if entry["name"].lower().endswith(".bin")
        }
        for name in layout["files"]:
            if name not in tracks or not _matches(
                _path(candidate.parent, name), tracks[name]["sha256"]
            ):
                raise RuntimeSetupError(
                    "A game track is missing or differs from the verified revision."
                )
    except (bofkit.KitError, OSError, ValueError) as error:
        raise RuntimeSetupError("The verified game could not be read.") from error
    return candidate


def game_launch_status(private_root: Path, game: str, channel: str = "play") -> dict:
    """Report readiness for the selected revision. The library remains available on a hold."""
    status = runtime_status(private_root, channel)
    if game not in ("bof3", "bof4"):
        raise RuntimeSetupError("Select one of the two supported game revisions.")
    status.update(game=game, compatibility_blocked=False)
    if game == "bof4":
        status.update(
            can_launch=False,
            compatibility_blocked=True,
            reason="This DuckStation version adds two seconds to disc track 2 and the end of Breath of Fire IV. A verified playback route is required.",
        )
    return status


@contextlib.contextmanager
def _operation_lock(lock: Path, busy_message: str):
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            acquire = partial(msvcrt.locking, handle.fileno(), msvcrt.LK_NBLCK, 1)
            release = partial(msvcrt.locking, handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            acquire = partial(
                fcntl.flock, handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
            )
            release = partial(fcntl.flock, handle.fileno(), fcntl.LOCK_UN)
        try:
            acquire()
        except OSError as error:
            raise RuntimeSetupError(busy_message) from error
        try:
            yield
        finally:
            handle.seek(0)
            release()


def _channel_lock(root: Path, channel: str):
    _component("duckstation", channel)
    return _operation_lock(
        _path(root, channel, "game-operation.lock"),
        "Another operation is using this game channel.",
    )


def _stop_unregistered_runtime(process: subprocess.Popen) -> None:
    """Reap a child launched by the current operation if its registration failed."""
    try:
        if process.poll() is None:
            process.terminate()
    except ProcessLookupError:
        pass
    process.wait(timeout=10)


@contextlib.contextmanager
def reserve_idle_channel(private_root: Path, channel: str = "lab"):
    """Prevent managed launches while taking a closed-channel snapshot or changing a profile."""
    with _channel_lock(private_root, channel):
        if _is_active(private_root, channel):
            raise RuntimeSetupError(
                "Close the running game before changing this channel."
            )
        yield


def launch_game(
    private_root: Path, game: str, cue: Path, channel: str = "play", *,
    library_root: Path | None = None, gameplay: dict[str, str] | None = None,
    presentation: str | None = None, fast_forward: bool | None = None,
    checkpoint_controls: dict[str, list[str]] | None = None, resume: bool = False,
) -> subprocess.Popen:
    """Return the owned stock process. The caller can wait for exit and restore focus."""
    _check_windows()
    directory = _installation(private_root, channel, "duckstation")
    candidate = _verified_cue(private_root if library_root is None else library_root, game, cue)
    with _channel_lock(private_root, channel):
        status = game_launch_status(private_root, game, channel)
        if not status["can_launch"]:
            raise RuntimeSetupError(status["reason"])
        _verify_installation(private_root, channel, "duckstation")
        firmware = _selected_firmware(private_root, channel, directory)
        _review_game_settings(directory, game, firmware["filename"])
        if gameplay is not None and channel == "lab":
            _configure_lab_controller(directory, game, gameplay)
        if presentation is not None or fast_forward is not None:
            if (game, channel) != ("bof3", "lab"):
                raise RuntimeSetupError("These display and speed options are available for III in Lab.")
            _configure_lab_preferences(directory, presentation, fast_forward, gameplay)
        checkpoint_files = {}
        args = [status["executable"], "-batch", "-slowboot"]
        if checkpoint_controls is not None:
            if (game, channel) != ("bof3", "lab"):
                raise RuntimeSetupError("Checkpoints are available in the III Lab.")
            checkpoint_files = _configure_checkpoints(directory, checkpoint_controls, fast_forward is True)
        if resume:
            if not checkpoint_files or library_root is None:
                raise RuntimeSetupError("Resume requires an isolated Lab installation.")
            state = _path(private_root, "resume.sav")
            if not state.is_file():
                raise RuntimeSetupError("The isolated checkpoint is missing.")
            args.extend(["-statefile", str(state)])
        if checkpoint_files:
            from .checkpoints import file_stamp
        before = {kind: file_stamp(path) for kind, path in checkpoint_files.items()}
        executable = status["executable"]
        process = subprocess.Popen(
            [*args, "--", str(candidate)], cwd=directory
        )
        try:
            identity = _process_identity(process.pid)
            if identity is None:
                raise RuntimeSetupError("The runtime exited before the game started.")
            _atomic_json(
                _path(private_root, channel, "active-game.json"),
                {
                    "pid": process.pid,
                    "created": identity[1],
                    "executable": executable,
                    "game": game,
                    "firmware_sha256": status["firmware_sha256"],
                    "runtime": status["version"],
                },
            )
        except Exception:
            _stop_unregistered_runtime(process)
            raise
        process.atelier_checkpoints = {kind: (path, before[kind]) for kind, path in checkpoint_files.items()}
        return process


def _configure_checkpoints(directory: Path, controls: dict[str, list[str]], fast: bool) -> dict[str, Path]:
    folder = "atelier-states"
    hotkeys = {
        "SaveGameState1": controls["quick"], "SaveSelectedSaveState": [],
        "LoadSelectedSaveState": [], "PowerOff": controls["suspend"],
    }
    if fast:
        hotkeys["FastForward"] = controls["speed"]
    _rewrite_settings(_path(directory, "settings.ini"), {
        "Hotkeys": hotkeys,
        "Folders": {"SaveStates": folder},
        "Main": {"SaveStateOnExit": "true", "LoadDevicesFromSaveStates": "false"},
    })
    effective = _effective_game_settings(directory, "bof3")
    if (effective.get("Folders", "SaveStates", fallback="") != folder
            or effective.getboolean("Main", "LoadDevicesFromSaveStates", fallback=False)
            or not effective.getboolean("Main", "SaveStateOnExit", fallback=False)):
        raise RuntimeSetupError("A custom Lab override conflicts with the checkpoint settings.")
    # In this pinned build the registered SaveGameState1 action writes the global slot.
    # The folder belongs solely to the managed III Lab route.
    return {"quick": _path(directory, folder, "savestate_1.sav"),
            "suspend": _path(directory, folder, "SLUS-00422_resume.sav")}


def _configure_lab_controller(directory: Path, game: str, gameplay: dict[str, str]) -> None:
    from .runtime_input import duckstation_changes

    settings = _path(directory, "settings.ini")
    config = configparser.ConfigParser(strict=False, interpolation=None)
    config.read_string(settings.read_text(encoding="utf-8-sig"))
    folder = PureWindowsPath(config.get("Folders", "GameSettings", fallback="gamesettings"))
    serial = {"bof3": "SLUS-00422", "bof4": "SLUS-01324"}[game]
    override = _path(directory, *folder.parts, serial + ".ini")
    if override.is_file():
        game_config = configparser.ConfigParser(strict=False, interpolation=None)
        game_config.read_string(override.read_text(encoding="utf-8-sig"))
        if (game_config.getboolean("ControllerPorts", "UseGameSettingsForController", fallback=False)
                or game_config.get("ControllerPorts", "InputProfileName", fallback="")):
            raise RuntimeSetupError(
                "This Lab game has its own controller profile. Use that profile or turn off Atelier gameplay mapping."
            )
    changes = duckstation_changes(settings, gameplay)
    if game == "bof3":
        changes["Pad1"]["Type"] = "DigitalController"
    backup = _path(directory, "settings.before-atelier-controller.ini")
    if not backup.exists():
        from .local_store import atomic_bytes
        atomic_bytes(backup, settings.read_bytes())
    _rewrite_settings(settings, changes)


def _configure_lab_preferences(directory: Path, presentation: str | None,
                               fast_forward: bool | None, gameplay: dict[str, str] | None) -> None:
    from .runtime_input import _retained_bindings, hold_bindings

    settings = _path(directory, "settings.ini")
    baseline = _path(directory, "settings.before-atelier-preferences.ini")
    if not baseline.exists():
        local_store.atomic_bytes(baseline, settings.read_bytes())
    original = configparser.ConfigParser(strict=False, interpolation=None)
    original.read_string(baseline.read_text(encoding="utf-8-sig"))
    changes = {}
    if presentation is not None:
        if presentation not in ("original", "crisp"):
            raise RuntimeSetupError("Choose Original or Crisp Pixels.")
        scaling = "NearestInteger" if presentation == "crisp" else original.get(
            "Display", "Scaling", fallback="BilinearSmooth",
        )
        changes["Display"] = {"Scaling": scaling}
    if fast_forward is not None:
        changes["Main"] = {"FastForwardSpeed": "2" if fast_forward else
                           original.get("Main", "FastForwardSpeed", fallback="0")}
        changes.setdefault("Display", {})["ShowSpeed"] = "true" if fast_forward else original.get(
            "Display", "ShowSpeed", fallback="false",
        )
        changes["Hotkeys"] = {"FastForward": (
            hold_bindings(baseline, gameplay) if fast_forward else
            _retained_bindings(baseline, {"Hotkeys": {"FastForward"}}, keep_sdl=True)
            .get(("Hotkeys", "FastForward"), [])
        )}
    _rewrite_settings(settings, changes)
    actual = _effective_game_settings(directory, "bof3")
    for section, key in (("Display", "Scaling"), ("Main", "FastForwardSpeed")):
        expected = changes.get(section, {}).get(key)
        if expected is not None and actual.get(section, key, fallback="") != expected:
            raise RuntimeSetupError("A per-game settings override is preventing the selected Lab option.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("status", "prepare", "repair", "import-package", "lab-openbios"),
    )
    parser.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE)
    parser.add_argument("--channel", choices=("play", "lab"), default="play")
    parser.add_argument(
        "--backend",
        choices=("duckstation", "pcsx-redux", "pcsx-redux-cli"),
        default="duckstation",
    )
    parser.add_argument(
        "--source", type=Path, help="Owner-selected, unchanged official package ZIP."
    )
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare_runtime(args.private_root, args.channel, args.backend)
        elif args.action == "repair":
            result = repair_runtime(args.private_root, args.channel, args.backend)
        elif args.action == "import-package":
            if args.source is None:
                parser.error("import-package requires --source")
            result = import_runtime_package(
                args.private_root, args.source, args.channel, args.backend
            )
        elif args.action == "lab-openbios":
            result = use_lab_openbios(args.private_root)
        else:
            result = runtime_status(args.private_root, args.channel)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, RuntimeSetupError, zipfile.BadZipFile) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
