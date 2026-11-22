"""Bounded ZIP and 7-Zip decoding for the private disc importer."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes as ct
import ctypes.util
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import stat
import unicodedata
from zipfile import ZipFile


class ImportFailure(ValueError):
    """The selected input or destination needs attention."""


@dataclass(frozen=True)
class Limits:
    members: int = 128
    total_bytes: int = 2 * 1024**3
    member_bytes: int = 1024**3
    archive_bytes: int = 2 * 1024**3
    ratio: int = 250
    reserve_bytes: int = 16 * 1024**2
    seconds: float = 600
    worker_bytes: int = 512 * 1024**2


@dataclass(frozen=True)
class Member:
    name: str
    size: int
    directory: bool = False


def relative_name(raw: str, directory: bool = False) -> str:
    name = raw.replace('\\', '/')
    if directory and name.endswith('/'):
        name = name[:-1]
    parts = name.split('/')
    if (not name or len(name) > 900 or len(parts) > 16 or PureWindowsPath(name).drive or
            any(not part or part.startswith('.') or part.endswith((' ', '.')) or len(part) > 180 or
                any(ord(c) < 32 or c in '<>:"|?*' for c in part) for part in parts)):
        raise ImportFailure(f'Unsafe or unsupported path {raw!r}.')
    devices = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'}
    devices.update(prefix + n for prefix in ('COM', 'LPT') for n in '0123456789¹²³')
    if any(part.split('.', 1)[0].rstrip().upper() in devices for part in parts):
        raise ImportFailure(f'Reserved device name in {raw!r}.')
    return name


def is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def check_members(entries: list[Member], compressed: int | None, root: Path, limits: Limits) -> int:
    if not entries or len(entries) > limits.members:
        raise ImportFailure('Archive is empty or exceeds the entry limit.')
    seen: dict[str, tuple[str, bool]] = {}
    explicit: set[str] = set()
    total = cues = bins = 0
    for entry in entries:
        name = relative_name(entry.name, entry.directory)
        parts = name.split('/')
        for i in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:i])
            key = unicodedata.normalize('NFC', prefix).casefold()
            value = (prefix, i < len(parts) or entry.directory)
            if key in seen and seen[key] != value:
                raise ImportFailure(f'Conflicting archive paths at {prefix!r}.')
            seen[key] = value
        if key in explicit:
            raise ImportFailure(f'Duplicate archive entry {name!r}.')
        explicit.add(key)
        if entry.directory:
            if entry.size != 0:
                raise ImportFailure('Directory has an unexpected payload.')
            continue
        suffix = PurePosixPath(name).suffix.lower()
        if suffix not in {'.cue', '.bin'}:
            raise ImportFailure(f'Unexpected archive member {name!r}. Select only a CUE/BIN game image.')
        if entry.size <= 0 or entry.size > limits.member_bytes or (suffix == '.cue' and entry.size > 1024**2):
            raise ImportFailure(f'File size outside the import limits for {name!r}.')
        if suffix == '.bin' and entry.size % 2352:
            raise ImportFailure(f'{name!r} is not a raw 2352-byte-sector track.')
        cues += suffix == '.cue'
        bins += suffix == '.bin'
        total += entry.size
    if cues != 1 or not bins:
        raise ImportFailure('Select one game with exactly one CUE and at least one BIN.')
    if total > limits.total_bytes or (compressed is not None and total > compressed * limits.ratio):
        raise ImportFailure('Archive exceeds the permitted expanded size or compression ratio.')
    if shutil.disk_usage(root).free < total + limits.reserve_bytes:
        raise ImportFailure(f'Insufficient space. Import requires {total + limits.reserve_bytes:,} free bytes.')
    return total


def format_of(prefix: bytes) -> str | None:
    if prefix.startswith(b'7z\xbc\xaf\x27\x1c'):
        return '7z'
    if prefix.startswith((b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')):
        return 'zip'
    return None


def reject_host_executable(prefix: bytes) -> None:
    magic = (b'MZ', b'\x7fELF', b'#!', b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe',
             b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe')
    if prefix.startswith(magic):
        raise ImportFailure('Unexpected host executable or script in the game image set.')


def copy_member(entry: Member, root: Path, read, done: int, total: int, report) -> int:
    dest = root.joinpath(*PurePosixPath(entry.name).parts)
    if entry.directory:
        dest.mkdir(parents=True, exist_ok=True)
        return done
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with dest.open('xb') as target:
        while data := read(min(1024**2, entry.size - written + 1)):
            if not written:
                reject_host_executable(data[:16])
            written += len(data)
            if written > entry.size:
                raise ImportFailure(f'Expanded data exceeds the declared size for {entry.name!r}.')
            target.write(data)
            report('copying', done + written, total)
    if written != entry.size:
        raise ImportFailure(f'Truncated member {entry.name!r}.')
    return done + written


def zip_import(path: Path, stage: Path, limits: Limits, report) -> None:
    with ZipFile(path) as archive:
        members: list[Member] = []
        for info in archive.infolist():
            if len(members) >= limits.members:
                raise ImportFailure('Archive exceeds the entry limit.')
            mode = stat.S_IFMT(info.external_attr >> 16) if info.create_system == 3 else 0
            if (info.flag_bits & 1 or info.orig_filename != info.filename or info.external_attr & 0x400 or
                    mode not in (0, stat.S_IFREG, stat.S_IFDIR) or (mode == stat.S_IFDIR and not info.is_dir())):
                raise ImportFailure('Encrypted files, links, special files or ambiguous ZIP names are unsupported.')
            members.append(Member(relative_name(info.filename, info.is_dir()), info.file_size, info.is_dir()))
        total = check_members(members, path.stat().st_size, stage, limits)
        report('copying', 0, total)
        done = 0
        for entry, info in zip(members, archive.infolist(), strict=True):
            with archive.open(info) as stream:
                done = copy_member(entry, stage, stream.read, done, total, report)


class SevenZip:
    """Use libarchive's regular-file reader. No archive entry is extracted by libarchive itself."""

    def __init__(self):
        name = ct.util.find_library('archive')
        if os.name == 'nt':
            # Windows' signed bsdtar component. Packaged builds may supply an audited archive.dll beside this module.
            bundled = Path(__file__).resolve().with_name('archive.dll')
            name = str(bundled) if bundled.is_file() else str(Path(os.environ['SystemRoot']) / 'System32' / 'archiveint.dll')
        if not name:
            raise ImportFailure('7-Zip support is unavailable. Repair the archive component or choose a local CUE.')
        try:
            self.dll = ct.CDLL(name)
            signatures = {
                'archive_read_new': (ct.c_void_p, []), 'archive_read_free': (ct.c_int, [ct.c_void_p]),
                'archive_read_support_format_7zip': (ct.c_int, [ct.c_void_p]),
                'archive_read_open_filename': (ct.c_int, [ct.c_void_p, ct.c_char_p, ct.c_size_t]),
                'archive_read_next_header': (ct.c_int, [ct.c_void_p, ct.POINTER(ct.c_void_p)]),
                'archive_error_string': (ct.c_char_p, [ct.c_void_p]),
                'archive_entry_pathname_w': (ct.c_wchar_p, [ct.c_void_p]),
                'archive_entry_pathname_utf8': (ct.c_char_p, [ct.c_void_p]),
                'archive_entry_filetype': (ct.c_uint, [ct.c_void_p]), 'archive_entry_size': (ct.c_int64, [ct.c_void_p]),
                'archive_entry_symlink': (ct.c_void_p, [ct.c_void_p]), 'archive_entry_hardlink': (ct.c_void_p, [ct.c_void_p]),
                'archive_entry_is_encrypted': (ct.c_int, [ct.c_void_p]),
                'archive_read_data': (ct.c_ssize_t, [ct.c_void_p, ct.c_void_p, ct.c_size_t]),
            }
            if os.name == 'nt':
                signatures['archive_read_open_filename_w'] = (ct.c_int, [ct.c_void_p, ct.c_wchar_p, ct.c_size_t])
            for func, (rtype, args) in signatures.items():
                symbol = getattr(self.dll, func)
                symbol.restype = rtype
                symbol.argtypes = args
        except (OSError, AttributeError) as err:
            raise ImportFailure('The libarchive component is missing or incompatible. Repair it or select a local CUE.') from err

    def checked(self, handle, result):
        if result < 0:
            detail = self.dll.archive_error_string(handle) or b'archive decoder failure'
            raise ImportFailure(detail.decode('utf-8', errors='replace')[:350])
        return result

    @contextmanager
    def opened(self, path: Path):
        handle = self.dll.archive_read_new()
        if not handle:
            raise ImportFailure('The archive reader could not allocate memory.')
        try:
            self.checked(handle, self.dll.archive_read_support_format_7zip(handle))
            if os.name == 'nt':
                self.checked(handle, self.dll.archive_read_open_filename_w(handle, str(path), 65536))
            else:
                self.checked(handle, self.dll.archive_read_open_filename(handle, os.fsencode(path), 65536))
            yield handle
        finally:
            self.dll.archive_read_free(handle)

    def entries(self, handle, limits: Limits):
        header = ct.c_void_p()
        for i in range(limits.members + 1):
            result = self.checked(handle, self.dll.archive_read_next_header(handle, ct.byref(header)))
            if result == 1:
                return
            if i == limits.members or result != 0:
                raise ImportFailure('Archive entry limit exceeded or invalid archive header.')
            kind = self.dll.archive_entry_filetype(header)
            if (kind not in (stat.S_IFDIR, stat.S_IFREG) or self.dll.archive_entry_symlink(header) or
                    self.dll.archive_entry_hardlink(header) or self.dll.archive_entry_is_encrypted(header)):
                raise ImportFailure('Links, encrypted entries and special files are unsupported.')
            raw = self.dll.archive_entry_pathname_utf8(header)
            name = raw.decode('utf-8') if raw else self.dll.archive_entry_pathname_w(header)
            if not name:
                raise ImportFailure('Unreadable archive member name.')
            directory = kind == stat.S_IFDIR
            yield Member(relative_name(name, directory), int(self.dll.archive_entry_size(header)), directory)

    def extract(self, path: Path, stage: Path, limits: Limits, report) -> None:
        with self.opened(path) as handle:
            listed = list(self.entries(handle, limits))
        total = check_members(listed, path.stat().st_size, stage, limits)
        report('copying', 0, total)
        with self.opened(path) as handle:
            done = 0
            buffer = ct.create_string_buffer(1024**2)

            def read(size: int) -> bytes:
                count = self.checked(handle, self.dll.archive_read_data(handle, buffer, size))
                return ct.string_at(buffer, count) if count else b''

            for expected, current in zip(listed, self.entries(handle, limits), strict=True):
                if current != expected:
                    raise ImportFailure('The archive changed after preflight.')
                done = copy_member(current, stage, read, done, total, report)


def limit_decoder_memory(size: int):
    if os.name != 'nt':
        import resource
        _, hard = resource.getrlimit(resource.RLIMIT_AS)
        ceiling = size if hard == resource.RLIM_INFINITY else min(size, hard)
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))
        return
    from ctypes import wintypes as wt

    class BasicLimits(ct.Structure):
        _fields_ = [('process_time', ct.c_int64), ('job_time', ct.c_int64), ('flags', wt.DWORD),
                    ('min_working', ct.c_size_t), ('max_working', ct.c_size_t), ('active', wt.DWORD),
                    ('affinity', ct.c_size_t), ('priority', wt.DWORD), ('scheduling', wt.DWORD)]

    class ExtendedLimits(ct.Structure):
        _fields_ = [('basic', BasicLimits), ('io_counts', ct.c_uint64 * 6), ('process_memory', ct.c_size_t),
                    ('job_memory', ct.c_size_t), ('peak_process', ct.c_size_t), ('peak_job', ct.c_size_t)]

    kernel = ct.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ct.c_void_p, wt.LPCWSTR]
    kernel.CreateJobObjectW.restype = wt.HANDLE
    kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wt.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    conf = ExtendedLimits()
    conf.basic.flags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    conf.process_memory = size
    if not job or not kernel.SetInformationJobObject(job, 9, ct.byref(conf), ct.sizeof(conf)) or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise ImportFailure(f'The archive worker memory limit could not be enabled (Windows error {ct.get_last_error()}).')
    # The worker owns this handle for its lifetime. The OS closes it on exit.


def run_decoder(path: str, format_name: str, destination: str, limits: Limits, pipe) -> None:
    import multiprocessing
    from multiprocessing.connection import wait
    from threading import Thread
    import time
    try:
        parent = multiprocessing.parent_process()
        if parent:
            def watch_parent():
                wait([parent.sentinel])
                os._exit(2)
            Thread(target=watch_parent, daemon=True).start()
        limit_decoder_memory(limits.worker_bytes)
        last_report = 0.0

        def update(phase, done, total):
            nonlocal last_report
            now = time.monotonic()
            if done == 0 or done == total or now - last_report >= 0.12:
                pipe.send(('progress', phase, done, total))
                last_report = now

        if format_name == '7z':
            SevenZip().extract(Path(path), Path(destination), limits, update)
        else:
            zip_import(Path(path), Path(destination), limits, update)
        pipe.send(('complete',))
    except (BrokenPipeError, EOFError):
        pass  # Cancellation closes the parent's endpoint.
    except Exception as exc:
        try:
            pipe.send(('error', str(exc)[:500] or type(exc).__name__))
        except (BrokenPipeError, EOFError):
            pass
    finally:
        pipe.close()
