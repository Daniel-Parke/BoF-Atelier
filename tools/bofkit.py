#!/usr/bin/env python3
"""Conservative, dependency-free setup utilities for the BoF Atelier seed.

These utilities do not implement the proposed Player or modify emulator settings.
Launch and backup are previews unless explicitly executed. Game bytes stay private.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile
from typing import Any, Iterable

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT_FILES = {
    'README.md', '00-START-HERE.md', '01-MASTER-PROMPT.md', '02-PLAY-NOW.md',
    '03-HANDOVER-STATE.md', 'START_HERE.html', 'AGENTS.md', 'SECURITY.md',
    'LICENSE-NOTE.md', '.gitignore', 'KIT-CONTENTS.json', 'SOURCE-CONTENTS.json',
}
PUBLIC_DIRECTORIES = {'context', 'docs', 'design', 'research', 'schemas', 'examples',
                      'templates', 'tools', 'tests', 'verification', 'planning', 'shell'}
PUBLIC_EXTENSIONS = {'.md', '.txt', '.json', '.py', '.html', '.css', '.js', '.toml', '.yml', '.yaml',
                     '.qml', '.ts', '.rs', '.lock', '.qrc', '.spec', '.ps1', '.cmd'}
FORBIDDEN_EXTENSIONS = {
    '.bin', '.iso', '.chd', '.cue', '.7z', '.zip', '.rar', '.ecm', '.mdf', '.mds',
    '.ccd', '.img', '.pbp', '.exe', '.dll', '.appimage', '.dmg', '.mcd', '.mcr',
    '.mc', '.sav', '.srm', '.state', '.psf', '.psflib', '.wav', '.mp3', '.flac',
    '.ogg', '.mp4', '.mkv', '.pem', '.key', '.p12', '.pfx', '.ttf', '.otf', '.woff', '.woff2',
    '.sqlite3', '.gme', '.mcs',
}
FORBIDDEN_PARTS = {'private', '.local', 'runtime', 'downloads', 'outputs', 'captures',
                   'logs', 'backups', 'upstream', 'vendor-private', '.git', '__pycache__',
                   '.venv', 'node_modules', 'target', 'dist', 'build', 'bof-atelier-seed-pack'}
BUILD_ONLY_PATHS = {'shell/tauri/gen', 'shell/tauri/icons'}
SECRET_PATTERNS = [
    re.compile(rb'rdpk-[A-Za-z0-9_-]{20,}'),
    re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'),
    re.compile(rb'sk-proj-[A-Za-z0-9_-]{30,}'),
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
]


class KitError(RuntimeError):
    """A user-actionable validation or safety failure."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(root: Path, relative: str, *, must_exist: bool = True) -> Path:
    """Resolve a portable relative path, rejecting escape and symlink components."""
    portable = relative.replace('\\', '/')
    parts = PurePosixPath(portable).parts
    windows = PureWindowsPath(relative)
    if not parts or PurePosixPath(portable).is_absolute() or windows.is_absolute() or windows.drive:
        raise KitError(f'Expected a relative path: {relative!r}')
    if '..' in parts or any(':' in part for part in parts):
        raise KitError(f'Unsafe path: {relative!r}')
    resolved_root = root.resolve()
    current = resolved_root
    for part in parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise KitError(f'Symlink is not allowed: {relative!r}')
    resolved = current.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise KitError(f'Path leaves the selected root: {relative!r}')
    if must_exist and not resolved.exists():
        raise KitError(f'Missing file: {relative}')
    return resolved


def parse_cue(cue_path: Path) -> dict[str, Any]:
    """Read a bounded CUE descriptor, preserving track types and indices."""
    if cue_path.stat().st_size > 1024 * 1024:
        raise KitError('CUE exceeds the 1 MiB safety limit.')
    text = cue_path.read_text(encoding='utf-8-sig')
    files: list[str] = []
    tracks: list[dict[str, Any]] = []
    current_file: str | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        file_match = re.match(r'^\s*FILE\s+"([^"]+)"\s+(\S+)\s*$', line, re.I)
        if file_match:
            if file_match[2].upper() != 'BINARY':
                raise KitError(f'Only BINARY CUE files are handled by this seed (line {line_number}).')
            current_file = file_match[1]
            safe_relative_path(cue_path.parent, current_file)
            files.append(current_file)
            continue
        if re.match(r'^\s*FILE\b', line, re.I):
            raise KitError(f'Unsupported or malformed FILE record on line {line_number}.')
        track_match = re.match(r'^\s*TRACK\s+(\d+)\s+(\S+)\s*$', line, re.I)
        if track_match:
            if current_file is None:
                raise KitError('TRACK appears before FILE.')
            tracks.append({'number': int(track_match[1]), 'mode': track_match[2].upper(),
                           'file': current_file, 'indices': {}})
            continue
        index_match = re.match(r'^\s*INDEX\s+(\d+)\s+(\d+):(\d+):(\d+)\s*$', line, re.I)
        if index_match:
            if not tracks:
                raise KitError('INDEX appears before TRACK.')
            minute, second, frame = (int(index_match[i]) for i in (2, 3, 4))
            if second >= 60 or frame >= 75:
                raise KitError(f'Invalid CUE time on line {line_number}.')
            index_number = index_match[1].zfill(2)
            if index_number in tracks[-1]['indices']:
                raise KitError('Duplicate CUE index.')
            tracks[-1]['indices'][index_number] = (minute * 60 + second) * 75 + frame
            continue
        if not line.strip() or re.match(r'^\s*REM\b', line, re.I):
            continue
        # Other valid CUE metadata is not interpreted by this limited reader.
        if re.match(r'^\s*(TITLE|PERFORMER|SONGWRITER|CATALOG|ISRC|FLAGS|PREGAP|POSTGAP|CDTEXTFILE)\b', line, re.I):
            raise KitError(f'Additional CUE directive needs manual review (line {line_number}).')
        raise KitError(f'Unknown CUE syntax on line {line_number}.')
    if not files or not tracks:
        raise KitError('CUE contains no usable FILE/TRACK records.')
    numbers = [track['number'] for track in tracks]
    if len(numbers) != len(set(numbers)) or numbers != sorted(numbers):
        raise KitError('Duplicate or unordered track numbers.')
    last_index_by_file: dict[str, int] = {}
    for track in tracks:
        if track['mode'] not in {'AUDIO', 'MODE1/2352', 'MODE2/2352'}:
            raise KitError(f'Unsupported seed track mode: {track["mode"]}')
        if '01' not in track['indices']:
            raise KitError('Each track needs INDEX 01.')
        target = safe_relative_path(cue_path.parent, track['file'])
        if not target.is_file() or target.stat().st_size % 2352:
            raise KitError(f'Not a sector-aligned raw track: {target.name}')
        sector_count = target.stat().st_size // 2352
        index = track['indices']['01']
        if index >= sector_count:
            raise KitError('CUE index exceeds its referenced file.')
        if '00' in track['indices'] and track['indices']['00'] > index:
            raise KitError('CUE pregap index follows INDEX 01.')
        if track['file'] in last_index_by_file and index <= last_index_by_file[track['file']]:
            raise KitError('Shared-file CUE track starts are not increasing.')
        last_index_by_file[track['file']] = index
    return {'files': files, 'tracks': tracks}


def load_inventory(root: Path) -> list[dict[str, Any]]:
    inventory_path = root / 'research/input-inventory.json'
    data = json.loads(inventory_path.read_text(encoding='utf-8'))
    if not isinstance(data, list):
        raise KitError('Unexpected inventory structure.')
    return data


def verify_inputs(root: Path, *, hashes: bool = True) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for game in load_inventory(root):
        for entry in game['entries']:
            row = {'game': game['game'], 'path': entry['kit_path']}
            try:
                path = safe_relative_path(root, entry['kit_path'], must_exist=False)
                if not path.exists():
                    row.update(status='MISSING')
                elif not path.is_file() or path.stat().st_size != entry['size']:
                    row.update(status='SIZE_MISMATCH')
                elif hashes and sha256_file(path) != entry['sha256']:
                    row.update(status='SHA256_MISMATCH')
                else:
                    row.update(status='SHA256_MATCH' if hashes else 'SIZE_MATCH')
            except (KitError, OSError) as error:
                row.update(status='ERROR', reason=str(error))
            results.append(row)
        working = game['working_cue']
        row = {'game': game['game'], 'path': working['path']}
        try:
            cue_path = safe_relative_path(root, working['path'], must_exist=False)
            if not cue_path.is_file():
                row.update(status='MISSING')
            elif sha256_file(cue_path) != working['sha256']:
                row.update(status='SHA256_MISMATCH')
            else:
                layout = parse_cue(cue_path)
                row.update(status='CUE_DEPENDENCIES_VALID', tracks=layout['tracks'])
        except (KitError, OSError, UnicodeError) as error:
            row.update(status='ERROR', reason=str(error))
        results.append(row)
    return results


def resolve_runtime(runtime_path: Path) -> Path:
    supplied = runtime_path.expanduser()
    if supplied.is_symlink():
        raise KitError('Select the actual runtime executable, not a symlink, for this helper.')
    if supplied.is_dir() and supplied.suffix.lower() == '.app':
        candidates = [supplied / 'Contents/MacOS' / name for name in ('DuckStation', 'duckstation-qt')]
        candidates = [candidate for candidate in candidates if candidate.is_file()]
        if len(candidates) != 1:
            raise KitError('Cannot identify the app executable. Select its actual executable explicitly.')
        supplied = candidates[0]
    resolved = supplied.resolve()
    if not resolved.is_file() or 'duckstation' not in resolved.name.lower():
        raise KitError('Select a trusted, separately installed DuckStation executable.')
    if os.name != 'nt' and not os.access(resolved, os.X_OK):
        raise KitError('The selected runtime is not executable. Follow its official installation instructions.')
    return resolved


def launch_command(root: Path, game_id: str, runtime_path: Path, *, resume: bool = False,
                   fullscreen: bool = True) -> list[str]:
    game = next((entry for entry in load_inventory(root) if entry['game'] == game_id), None)
    if game is None:
        raise KitError(f'Unknown game: {game_id}')
    cue_path = safe_relative_path(root, game['working_cue']['path'])
    if sha256_file(cue_path) != game['working_cue']['sha256']:
        raise KitError('Working descriptor changed: inspect before launching.')
    parse_cue(cue_path)
    runtime = resolve_runtime(runtime_path)
    command = [str(runtime)]
    if fullscreen:
        command.append('-fullscreen')
    if resume:
        command.append('-resume')
    command.extend(['--', str(cue_path)])
    return command


def save_candidates(source_root: Path) -> list[Path]:
    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise KitError('Save source must be a directory.')
    results: list[Path] = []
    for candidate in source_root.rglob('*'):
        if candidate.is_symlink():
            raise KitError(f'Symlink in save tree: {candidate.name}')
        lower_name = candidate.name.lower()
        if candidate.is_file() and (candidate.suffix.lower() in {'.mcd', '.mcr', '.mc', '.sav', '.srm', '.state'}
                                    or '.sav.' in lower_name or '.state.' in lower_name):
            results.append(candidate)
    if not results:
        raise KitError('No supported save/state files found. Select the actual runtime data/save directory.')
    return sorted(results)


def backup_saves(source_root: Path, destination_root: Path, *, execute: bool = False,
                 confirmed_closed: bool = False) -> dict[str, Any]:
    """Copy saves only; never restore or delete the source. Closed-state is user attested."""
    if source_root.is_symlink() or destination_root.is_symlink():
        raise KitError('Choose real directories rather than symlinks.')
    source_root = source_root.resolve()
    destination_root = destination_root.resolve()
    if destination_root == source_root or destination_root.is_relative_to(source_root):
        raise KitError('Backup destination must be outside the source directory.')
    candidates = save_candidates(source_root)
    total_bytes = sum(candidate.stat().st_size for candidate in candidates)
    if total_bytes > 10 * 1024**3:
        raise KitError('Backup exceeds the seed safety limit of 10 GiB; review the selected source.')
    report: dict[str, Any] = {'source': str(source_root), 'files': [str(p.relative_to(source_root)) for p in candidates],
                              'bytes': total_bytes, 'executed': execute,
                              'consistency': 'NOT_PROVEN; runtime-closed acknowledgement required'}
    if not execute:
        return report
    if not confirmed_closed:
        raise KitError('Close the emulator and pass --confirm-closed before executing a backup.')
    destination_root.mkdir(parents=True, exist_ok=True)
    identifier = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    staging = Path(tempfile.mkdtemp(prefix='.backup-staging-', dir=destination_root))
    final = destination_root / identifier
    entries = []
    try:
        for source in candidates:
            relative = source.relative_to(source_root)
            before = source.stat()
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied_digest = sha256_file(target)
            source_digest = sha256_file(source)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or copied_digest != source_digest:
                raise KitError(f'Source changed during backup: {relative}')
            entries.append({'path': relative.as_posix(), 'bytes': after.st_size, 'sha256': copied_digest})
        manifest = {'schema_version': 1, 'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'closed_runtime': 'user-attested, not independently observed',
                    'consistency': 'files_stable_during_copy; game-semantic validity not tested',
                    'entries': entries}
        (staging / 'backup-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        staging.rename(final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    report['destination'] = str(final)
    report['consistency'] = manifest['consistency']
    return report


def forbidden_public_path(relative: Path | str) -> bool:
    path = PurePosixPath(str(relative).replace('\\', '/'))
    name = path.name.lower()
    return (any(part.lower() in FORBIDDEN_PARTS for part in path.parts)
            or path.suffix.lower() in FORBIDDEN_EXTENSIONS
            or '.state.' in name or '.sav.' in name
            or name == '.env' or (name.startswith('.env.') and name != '.env.example')
            or name.endswith('.local.json') or name.endswith('.local.toml'))


def inspect_public_file(path: Path, relative: Path) -> bytes:
    if _linked(path):
        raise KitError(f'Public export refuses symlinks: {relative}')
    if forbidden_public_path(relative):
        raise KitError(f'Private/binary path in public selection: {relative}')
    if path.stat().st_size > 4 * 1024 * 1024:
        raise KitError(f'Large file needs explicit review before publication: {relative}')
    data = path.read_bytes()
    if b'\x00' in data:
        raise KitError(f'Binary bytes in a public text file: {relative}')
    try:
        data.decode('utf-8')
    except UnicodeDecodeError as error:
        raise KitError(f'Non-UTF8 file needs manual review: {relative}') from error
    if any(pattern.search(data) for pattern in SECRET_PATTERNS):
        raise KitError(f'Possible credential/private key in: {relative}; value is not displayed.')
    return data


def _linked(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def public_files(root: Path) -> list[Path]:
    selected: list[Path] = []
    for name in sorted(PUBLIC_ROOT_FILES):
        path = root / name
        if path.exists():
            inspect_public_file(path, Path(name))
            selected.append(path)
    for directory in sorted(PUBLIC_DIRECTORIES):
        base = root / directory
        if not base.exists():
            continue
        if _linked(base):
            raise KitError(f'Public root is a symlink: {directory}')
        for parent, directory_names, file_names in os.walk(base, followlinks=False):
            for name in list(directory_names):
                candidate = Path(parent) / name
                if _linked(candidate):
                    raise KitError(f'Symlink in public tree: {candidate.relative_to(root)}')
                if (name.lower() in FORBIDDEN_PARTS or
                        candidate.relative_to(root).as_posix().lower() in BUILD_ONLY_PATHS):
                    directory_names.remove(name)
            for name in file_names:
                candidate = Path(parent) / name
                relative = candidate.relative_to(root)
                if (candidate.name != '.gitignore' and relative.as_posix() != 'shell/linux/Dockerfile'
                        and candidate.suffix.lower() not in PUBLIC_EXTENSIONS):
                    raise KitError(f'Unallowlisted file type in public tree: {relative}')
                inspect_public_file(candidate, relative)
                selected.append(candidate)
    return sorted(set(selected))


def export_public(root: Path, output_path: Path) -> dict[str, Any]:
    root = root.resolve()
    output_path = output_path.expanduser().resolve()
    if output_path.is_relative_to(root):
        raise KitError('Write the export outside the workspace to avoid recursive packaging.')
    if output_path.exists():
        raise KitError('Export already exists; choose a new filename rather than overwrite it.')
    selected = public_files(root)
    current = root / 'SOURCE-CONTENTS.json'
    expected = None
    if current.is_file():
        rows = json.loads(current.read_bytes())['files']
        expected = {row['path']: row['sha256'] for row in rows}
        if len(expected) != len(rows) or set(expected) != {
                file.relative_to(root).as_posix() for file in selected if file != current}:
            raise KitError('The source allowlist differs from the current inventory. Review it before export.')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + '.partial-' + uuid.uuid4().hex[:8])
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=7) as archive:
            for file_path in selected:
                relative = file_path.relative_to(root)
                data = inspect_public_file(file_path, relative)
                if (expected is not None and file_path != current
                        and hashlib.sha256(data).hexdigest() != expected[relative.as_posix()]):
                    raise KitError(f'Source content differs from the reviewed inventory: {relative}')
                entry = zipfile.ZipInfo((Path(root.name) / relative).as_posix(), (1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=7)
        temporary.replace(output_path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {'path': str(output_path), 'files': len(selected), 'bytes': output_path.stat().st_size,
            'sha256': sha256_file(output_path),
            'status': 'ALLOWLISTED_CANDIDATE; owner review and rights clearance still required'}


def audit_git(root: Path) -> dict[str, Any]:
    top = subprocess.run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'],
                         capture_output=True, check=False)
    if top.returncode:
        raise KitError('No readable Git index here. No repository was initialised or modified.')
    root = Path(os.fsdecode(top.stdout).strip())
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '--cached', '-z'],
                            capture_output=True, check=False)
    if result.returncode:
        raise KitError('No readable Git index here. No repository was initialised or modified.')
    entries = [entry.decode('utf-8') for entry in result.stdout.split(b'\x00') if entry]
    problems = [entry for entry in entries if forbidden_public_path(entry)]
    for entry in entries:
        if entry in problems:
            continue
        staged = subprocess.run(['git', '-C', str(root), 'show', ':' + entry], capture_output=True, check=False)
        if staged.returncode:
            problems.append(entry + ' (index content unreadable)')
        elif len(staged.stdout) > 4 * 1024 * 1024 or b'\x00' in staged.stdout:
            problems.append(entry + ' (large/binary indexed content)')
        elif any(pattern.search(staged.stdout) for pattern in SECRET_PATTERNS):
            problems.append(entry + ' (possible secret)')
    return {'indexed_files': len(entries), 'problems': problems,
            'scope': 'current index only; historical commits and permissions require separate review'}


def doctor(root: Path, runtime: Path | None = None) -> dict[str, Any]:
    try:
        from .inspect_disc import DiscError, inspect_disc
    except ImportError:
        from inspect_disc import DiscError, inspect_disc
    inventory = load_inventory(root)
    games = []
    for game in inventory:
        observed_serial = None
        reference_match = False
        try:
            cue_path = safe_relative_path(root, game['working_cue']['path'])
            layout = parse_cue(cue_path)
            data_track = next(t for t in layout['tracks'] if t['mode'].startswith('MODE'))
            disc = inspect_disc(safe_relative_path(cue_path.parent, data_track['file']))
            observed_serial = disc['serial_from_system_cnf']
            reference_match = disc['executable_sha256'] == game['disc_inspection']['executable_sha256']
            state = 'descriptor and boot executable inspected'
        except (OSError, UnicodeError, KitError, DiscError, StopIteration) as error:
            state = str(error)
        games.append({'id': game['game'], 'serial': observed_serial,
                      'expected_serial': game['disc_inspection']['serial_from_system_cnf'],
                      'boot_digest_matches_inventory': reference_match,
                      'gameplay_validated': False, 'state': state})
    bios_directory = root / 'private/bios'
    bios_candidates = [path.name for path in bios_directory.glob('*') if path.is_file() and path.suffix.lower() == '.bin']
    runtime_state = 'no executable supplied to this diagnostic; use runtime_setup status for managed channels'
    if runtime is not None:
        runtime_state = str(resolve_runtime(runtime)) + ' (not executed or version-verified)'
    return {'workspace': str(root), 'host_platform': sys.platform, 'python': sys.version.split()[0],
            'games': games, 'bios_candidates_in_kit_folder': bios_candidates,
            'bios_status': 'NOT VALIDATED; external runtime may use its own BIOS directory',
            'runtime': runtime_state, 'paid_services': 'DISABLED / NO CREDENTIALS',
            'hardware_game_tests': 'not exercised by this diagnostic; see verification/CURRENT.md'}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    commands = parser.add_subparsers(dest='command', required=True)
    doctor_parser = commands.add_parser('doctor', help='Read-only local inventory; does not execute runtime.')
    doctor_parser.add_argument('--runtime', type=Path)
    verify_parser = commands.add_parser('verify', help='Verify supplied hashes and working CUE references.')
    verify_parser.add_argument('--sizes-only', action='store_true', help='Faster check; NOT a content-integrity check.')
    launch_parser = commands.add_parser('launch', help='Preview direct launch; pass --execute to run.')
    launch_parser.add_argument('--game', choices=['bof3', 'bof4'], required=True)
    launch_parser.add_argument('--runtime', type=Path, required=True)
    launch_parser.add_argument('--resume', action='store_true')
    launch_parser.add_argument('--ack-resume-risk', action='store_true')
    launch_parser.add_argument('--windowed', action='store_true')
    launch_parser.add_argument('--execute', action='store_true')
    backup_parser = commands.add_parser('backup', help='Preview a closed-runtime save backup.')
    backup_parser.add_argument('--source', type=Path, required=True)
    backup_parser.add_argument('--destination', type=Path, required=True)
    backup_parser.add_argument('--execute', action='store_true')
    backup_parser.add_argument('--confirm-closed', action='store_true')
    public_parser = commands.add_parser('export-public', help='Create a source-only candidate ZIP outside this folder.')
    public_parser.add_argument('--output', type=Path, required=True)
    commands.add_parser('audit-git', help='Inspect current Git index; never pushes or changes it.')
    arguments = parser.parse_args(argv)
    root = arguments.root.expanduser().resolve()
    try:
        if arguments.command == 'doctor':
            result = doctor(root, arguments.runtime)
        elif arguments.command == 'verify':
            result = {'checks': verify_inputs(root, hashes=not arguments.sizes_only), 'gameplay': 'NOT_TESTED'}
        elif arguments.command == 'launch':
            command = launch_command(root, arguments.game, arguments.runtime,
                                     resume=arguments.resume, fullscreen=not arguments.windowed)
            result = {'argument_array': command, 'execute': arguments.execute,
                      'warning': 'Uses the selected runtime\'s existing data/settings. No profile isolation is created.'}
            print(json.dumps(result, indent=2))
            if not arguments.execute:
                return 0
            if arguments.resume and not arguments.ack_resume_risk:
                raise KitError('Resume requires --ack-resume-risk after confirming runtime/state compatibility.')
            print('Launching the selected installed runtime; close it normally to finish this command.', flush=True)
            return subprocess.run(command, cwd=str(Path(command[0]).parent), check=False).returncode
        elif arguments.command == 'backup':
            result = backup_saves(arguments.source, arguments.destination,
                                  execute=arguments.execute, confirmed_closed=arguments.confirm_closed)
        elif arguments.command == 'export-public':
            result = export_public(root, arguments.output)
        else:
            result = audit_git(root)
        print(json.dumps(result, indent=2))
        if arguments.command == 'audit-git' and result['problems']:
            return 1
        if arguments.command == 'verify' and any(
                row['status'] not in {'SHA256_MATCH', 'SIZE_MATCH', 'CUE_DEPENDENCIES_VALID'}
                for row in result['checks']):
            return 1
        return 0
    except (OSError, ValueError, KeyError, KitError, UnicodeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
