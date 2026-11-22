"""Import a locally selected PlayStation disc into an isolated, recoverable library."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time
import uuid
import zlib
from typing import Callable
from threading import Event

if __package__:
    from . import bofkit
    from .archive_reader import ImportFailure, Limits, Member, check_members, copy_member, format_of, is_link, relative_name, run_decoder
    from .inspect_disc import DiscError, inspect_disc
else:
    import bofkit
    from archive_reader import ImportFailure, Limits, Member, check_members, copy_member, format_of, is_link, relative_name, run_decoder
    from inspect_disc import DiscError, inspect_disc

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = 'import-receipt.json'
FIXED_IV = 'Breath of Fire IV - filename-fixed.cue'
STAGING_MARK = b'BoF Atelier private import staging v1\n'
IV_CUE_SHA = 'edf89aba440e76ddba9d4a2b0f3ca8ea63614a84f817008418ff45326aa1dc7c'
IV_BIN_SHA = '0e8e4285f58a4be91cd7227ecd72ea59785f447a1a57b8b7daed48b5e857a0fa'
IV_SPLIT = 645_066_576
IV_REFERENCE = ('24be71b32aeb52a930bc08dccda5db61e904de8a', 'dc0fa59967976a4e37315a6b63a7bbbc9536a85a')
III_REFERENCE = ('5745d9dde965ed0ec673ba071deb762355fa3e1a', 'd9f92af296360772e62caa4cb276de3fa74f5538')
PROGRESS = Callable[[str, int, int], None]


def no_links(path: Path) -> None:
    for part in (*reversed(path.parents), path):
        if os.path.lexists(part) and is_link(part):
            raise ImportFailure(f'Select a real local path. Links and reparse points are unsupported: {part.name!r}.')


def file_id(path: Path) -> tuple[int, int, int, int]:
    record = path.stat()
    if not stat.S_ISREG(record.st_mode):
        raise ImportFailure('Select a regular local file.')
    return record.st_dev, record.st_ino, record.st_size, record.st_mtime_ns


def digest(path: Path, tick, *, split_iv: bool = False) -> dict:
    sha256 = hashlib.sha256()
    sha1 = hashlib.sha1(usedforsecurity=False)
    md5 = hashlib.md5(usedforsecurity=False)
    halves = [hashlib.sha1(usedforsecurity=False), hashlib.sha1(usedforsecurity=False)] if split_iv else []
    total = crc = 0
    with path.open('rb') as src:
        while block := src.read(2 * 1024**2):
            tick(len(block))
            for h in (sha256, sha1, md5):
                h.update(block)
            if halves:
                boundary = max(0, min(len(block), IV_SPLIT - total))
                halves[0].update(block[:boundary])
                halves[1].update(block[boundary:])
            crc = zlib.crc32(block, crc)
            total += len(block)
    info = dict(bytes=total, sha256=sha256.hexdigest(), sha1=sha1.hexdigest(), md5=md5.hexdigest(), crc32=f'{crc:08x}')
    if halves:
        info['reference_ranges_sha1'] = [h.hexdigest() for h in halves]
    return info


@contextmanager
def import_lock(control: Path, check):
    control.mkdir(exist_ok=True)
    no_links(control / 'library.lock')
    with (control / 'library.lock').open('a+b') as anchor:
        if not anchor.seek(0, os.SEEK_END):
            anchor.write(b'0')
            anchor.flush()
        while True:
            check()
            anchor.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(anchor.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(anchor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, PermissionError):
                time.sleep(0.1)
        try:
            yield
        finally:
            anchor.seek(0)
            if os.name == 'nt':
                msvcrt.locking(anchor.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(anchor, fcntl.LOCK_UN)


def remove_own_job(control: Path, job: Path) -> None:
    if (job.parent != control or not re.fullmatch(r'job-[0-9a-f]{32}', job.name) or is_link(job) or
            job.resolve().parent != control.resolve()):
        raise ImportFailure('Unexpected import staging directory. Review the private library before retrying.')
    marker = job / 'owner'
    if not os.path.lexists(marker) and not any(job.iterdir()):
        job.rmdir()
        return
    if not marker.is_file() or is_link(marker) or marker.stat().st_size != len(STAGING_MARK) or marker.read_bytes() != STAGING_MARK:
        raise ImportFailure('Unrecognised import staging directory. Existing data was retained.')
    shutil.rmtree(job)


def decode_archive(source: Path, form: str, stage: Path, limits: Limits, check, report):
    context = mp.get_context('spawn')
    reader, writer = context.Pipe(duplex=False)
    child = context.Process(target=run_decoder, args=(str(source), form, str(stage), limits, writer))
    child.start()
    writer.close()
    try:
        while True:
            check()
            if reader.poll(0.08):
                try:
                    message = reader.recv()
                except EOFError:
                    break
                if message[0] == 'progress':
                    report(*message[1:])
                elif message[0] == 'error':
                    raise ImportFailure(message[1])
                elif message[0] == 'complete':
                    return
            elif not child.is_alive():
                break
        raise ImportFailure('Archive worker stopped before completion. Check the archive or its resource limits.')
    finally:
        reader.close()
        child.join(0.15)
        if child.is_alive():
            child.terminate()
            child.join(2)
        if child.is_alive():
            child.kill()
            child.join()
        child.close()


def import_loose(cue: Path, stage: Path, limits: Limits, check, report):
    identity = file_id(cue)
    if identity[2] > 1024**2:
        raise ImportFailure('CUE exceeds 1 MiB.')
    raw = cue.read_bytes()
    original_digest = hashlib.sha256(raw).hexdigest()
    references = re.findall(r'^\s*FILE\s+"([^"\r\n]+)"\s+BINARY\s*$', raw.decode('utf-8-sig'), re.I | re.M)
    if not references or len(references) > limits.members:
        raise ImportFailure('CUE has no supported BINARY file list or exceeds the entry limit.')
    if original_digest == IV_CUE_SHA:
        references = [name + '.bin' if name == 'breath of fire 4' else name for name in references]
    targets = [relative_name(cue.name)] + list(dict.fromkeys(relative_name(n) for n in references))
    selected = {}
    for name in targets:
        path = cue.parent
        for part in Path(name).parts:
            check()
            with os.scandir(path) as siblings:
                found = any(entry.name == part for entry in siblings)
            if not found:
                raise ImportFailure(f'Missing or case-mismatched CUE member {name!r}.')
            path = path / part
            no_links(path)
        no_links(path)
        if not path.is_file():
            raise ImportFailure(f'Missing CUE member {name!r}. Select the descriptor beside its original tracks.')
        selected[name] = (path, file_id(path))
    entries = [Member(name, meta[2]) for name, (_, meta) in selected.items()]
    total = check_members(entries, None, stage, limits)
    done = 0
    for entry in entries:
        path, before = selected[entry.name]
        with path.open('rb') as stream:
            def update(phase, done, total):
                check()
                report(phase, done, total)
            done = copy_member(entry, stage, stream.read, done, total, update)
        if before != file_id(path):
            raise ImportFailure('A selected loose file changed during import.')
    if identity != file_id(cue) or hashlib.sha256((stage / cue.name).read_bytes()).hexdigest() != original_digest:
        raise ImportFailure('The selected CUE changed during import.')


def identify(stage: Path, form: str, source_digest, check, report) -> dict:
    paths = sorted((p for p in stage.rglob('*') if p.is_file()), key=lambda p: p.relative_to(stage).as_posix())
    total = sum(p.stat().st_size for p in paths)
    done = 0

    def count(length):
        nonlocal done
        check()
        done += length
        report('hashing', done, total)

    files = {}
    for path in paths:
        files[path] = digest(path, count, split_iv=path.suffix.lower() == '.bin' and path.stat().st_size == 688_315_152)
    cue = next(p for p in paths if p.suffix.lower() == '.cue')
    working = cue
    archives = bofkit.load_inventory(ROOT)
    measured_names = sorted((p.name, info['sha256']) for p, info in files.items())
    known = next((game for game in archives if measured_names == sorted(
        (Path(entry['name']).name, entry['sha256']) for entry in game['entries'])), None)
    if files[cue]['sha256'] == IV_CUE_SHA:
        binfile = cue.with_name('breath of fire 4.bin')
        if not known or known['game'] != 'bof4' or files.get(binfile, {}).get('sha256') != IV_BIN_SHA:
            raise ImportFailure('The IV filename correction requires the verified matching original CUE and BIN.')
        old = b'FILE "breath of fire 4" BINARY'
        data = cue.read_bytes()
        if data.count(old) != 1:
            raise ImportFailure('Unexpected filename substitution target.')
        working = cue.with_name(FIXED_IV)
        with working.open('xb') as output:
            output.write(data.replace(old, b'FILE "breath of fire 4.bin" BINARY', 1))
        if hashlib.sha256(working.read_bytes()).hexdigest() != known['working_cue']['sha256']:
            raise ImportFailure('The generated working CUE does not match the verified filename-only correction.')
    layout = bofkit.parse_cue(working)
    if [t['number'] for t in layout['tracks']] != list(range(1, len(layout['tracks']) + 1)) or len(layout['tracks']) > 99:
        raise ImportFailure('CUE tracks must be contiguous and numbered from 1 through 99.')
    used = set()
    last = {}
    prev_number = {}
    disk_names = {path.relative_to(working.parent).as_posix() for path in paths if path.is_relative_to(working.parent)}
    for track in layout['tracks']:
        name = relative_name(track['file'])
        member = working.parent / name
        if name not in disk_names or member.suffix.lower() != '.bin':
            raise ImportFailure('A CUE reference differs in case or does not name an imported BIN.')
        ordered = list(track['indices'].items())
        if ([int(i) for i, _ in ordered] != sorted(int(i) for i, _ in ordered) or
                any(i < last.get(name, 0) or i >= member.stat().st_size // 2352 for _, i in ordered) or
                [i for _, i in ordered] != sorted(i for _, i in ordered) or
                name in used and prev_number[name] != track['number'] - 1):
            raise ImportFailure('The CUE contains invalid track/index ordering or extents.')
        last[name] = ordered[-1][1]
        used.add(name)
        prev_number[name] = track['number']
    expected_bins = {p for p in paths if p.suffix.lower() == '.bin'}
    if {working.parent / name for name in used} != expected_bins:
        raise ImportFailure('Archive includes unreferenced BIN data. Select the correct disc set.')
    first_track = layout['tracks'][0]
    if first_track['mode'] == 'AUDIO' or first_track['indices']['01'] != 0:
        raise ImportFailure('This importer requires a raw PlayStation data track starting at index zero.')
    report('identifying', 0, 0)
    check()
    disc = inspect_disc(working.parent / first_track['file'])
    serial = disc['serial_from_system_cnf']
    game = (known['game'] if known else
            {'SLUS-00422':'bof3', 'SLUS-01324':'bof4'}.get(serial) or
            {'BREATH_OF_FIRE3':'bof3', 'BOF4':'bof4'}.get(disc['iso9660_volume'], 'unrecognised'))
    if known and (known['disc_inspection']['executable_sha256'] != disc['executable_sha256'] or
                  known['disc_inspection']['serial_from_system_cnf'] != serial):
        raise ImportFailure('Disc identification disagrees with the recorded source evidence.')
    if known:
        content_key = [files[cue]['sha256'], sorted(item['sha256'] for p, item in files.items() if p != cue)]
    else:
        content_key = [files[cue]['sha256'], [(name, files[working.parent / name]['sha256']) for name in layout['files']]]
    fingerprint = hashlib.sha256(json.dumps(content_key, separators=(',', ':')).encode()).hexdigest()
    track_hashes = [files[working.parent / t['file']]['sha1'] for t in layout['tracks']]
    ref_match = False
    ref_url = None
    if len(layout['tracks']) == 2 and game == 'bof3' and tuple(track_hashes) == III_REFERENCE:
        ref_match, ref_url = True, 'https://redump.info/disc/184'
    if game == 'bof4' and len(expected_bins) == 1 and tuple(files[next(iter(expected_bins))].get('reference_ranges_sha1', ())) == IV_REFERENCE:
        ref_match, ref_url = True, 'https://redump.info/disc/1222'
    warnings = []
    if working != cue:
        warnings.extend(['The working CUE corrects only the missing .bin filename. The original is preserved.',
                         'Track 2 omits INDEX 00. Verify runtime track timing against the reference before promoting this IV profile.'])
    if not known:
        warnings.append('Original play candidate. This input has no qualified enhancement or save-editing profile.')
    return {
        'schema_version': 1, 'game': game, 'library_id': game if known else f'{game}-{fingerprint[:16]}',
        'content_fingerprint': fingerprint, 'serial': serial, 'volume': disc['iso9660_volume'],
        'boot_executable': disc['boot_executable'], 'executable_sha256': disc['executable_sha256'],
        'iso_entries': disc['total_entries'], 'input_format': form, 'archive': source_digest,
        'source_attestation': 'user-selected private input', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'original_cue': cue.relative_to(stage).as_posix(), 'working_cue': working.relative_to(stage).as_posix(),
        'working_cue_sha256': hashlib.sha256(working.read_bytes()).hexdigest(), 'tracks': layout['tracks'],
        'entries': [dict(path=path.relative_to(stage).as_posix(), **info) for path, info in files.items()],
        'seed_entry_hashes_match': bool(known), 'reference_match': ref_match, 'reference_url': ref_url,
        'reference_scope': 'track data only' if ref_match else 'unmatched',
        'original_play_candidate': True, 'verified_patches_enabled': False, 'gameplay_validated': False, 'warnings': warnings,
    }


def verify_installed(directory: Path, candidate: dict, check) -> dict:
    no_links(directory / RECEIPT)
    try:
        manifest = directory / RECEIPT
        if not manifest.is_file() or manifest.stat().st_size > 1024**2:
            raise ValueError('missing or oversized receipt')
        saved = json.loads(manifest.read_text(encoding='utf-8'))
        if (saved.get('schema_version') != 1 or saved['content_fingerprint'] != candidate['content_fingerprint'] or
                saved['library_id'] != directory.name or not (1 <= len(saved['entries']) <= Limits().members)):
            raise ValueError('incompatible receipt')
        for key in ('game', 'serial', 'volume', 'executable_sha256', 'seed_entry_hashes_match', 'reference_match',
                    'working_cue_sha256', 'tracks', 'original_play_candidate', 'verified_patches_enabled'):
            if saved[key] != candidate[key]:
                raise ValueError('receipt identification mismatch')
        expected = sorted(e['sha256'] for e in candidate['entries'])
        if sorted(e['sha256'] for e in saved['entries']) != expected:
            raise ValueError('unexpected receipt hashes')
        for entry in saved['entries']:
            path = directory / relative_name(entry['path'])
            no_links(path)
            if not path.is_file() or path.stat().st_size != entry['bytes'] or digest(path, lambda n: check())['sha256'] != entry['sha256']:
                raise ValueError('original file mismatch')
        cue = directory / relative_name(saved['working_cue'])
        no_links(cue)
        if cue.stat().st_size > 1024**2 or hashlib.sha256(cue.read_bytes()).hexdigest() != candidate['working_cue_sha256']:
            raise ValueError('working descriptor mismatch')
        if bofkit.parse_cue(cue)['tracks'] != candidate['tracks']:
            raise ValueError('descriptor track mismatch')
        return saved
    except ImportFailure:
        raise
    except (KeyError, TypeError, OSError, ValueError, bofkit.KitError) as err:
        raise ImportFailure('The existing game or receipt differs from its measured input. Existing data was preserved.') from err


def import_game(source: Path, library: Path | None = None, *, cancel: Event | None = None,
                progress: PROGRESS | None = None, limits: Limits = Limits()) -> dict:
    source = Path(source).expanduser().absolute()
    library = Path(library if library is not None else ROOT / 'private' / 'games').expanduser().absolute()
    deadline = time.monotonic() + limits.seconds

    def check():
        if cancel is not None and cancel.is_set():
            raise ImportFailure('Import cancelled. Retry with the same source to resume setup.')
        if time.monotonic() >= deadline:
            raise ImportFailure('Import exceeded its time limit. No incomplete game was activated.')

    def report(phase, done=0, total=0):
        check()
        if progress:
            progress(phase, done, total)

    try:
        check()
        no_links(source)
        no_links(library)
        before = file_id(source)
        with source.open('rb') as src:
            form = format_of(src.read(16))
        if not form and source.suffix.lower() != '.cue':
            raise ImportFailure('Select a ZIP or 7-Zip archive, or a CUE beside its original BIN tracks.')
        if form and before[2] > limits.archive_bytes:
            raise ImportFailure('The selected archive exceeds the allowed compressed size.')
        library.mkdir(parents=True, exist_ok=True)
        control = library / '.atelier-import'
        no_links(control)
        report('preflight')
        with import_lock(control, check):
            for old in control.glob('job-*'):
                if re.fullmatch(r'job-[0-9a-f]{32}', old.name):
                    remove_own_job(control, old)
            job = control / f'job-{uuid.uuid4().hex}'
            job.mkdir()
            try:
                (job / 'owner').write_bytes(STAGING_MARK)
                stage = job / 'media'
                stage.mkdir()
                archive = None
                if form:
                    report('checking archive')
                    archive = digest(source, lambda n: check())
                    decode_archive(source, form, stage, limits, check, report)
                    if before != file_id(source) or digest(source, lambda n: check())['sha256'] != archive['sha256']:
                        raise ImportFailure('The selected archive changed during import.')
                else:
                    form = 'cue/bin'
                    import_loose(source, stage, limits, check, report)
                receipt = identify(stage, form, archive, check, report)
                final = library / receipt['library_id']
                no_links(final)
                if final.exists():
                    report('verifying existing game')
                    return dict(verify_installed(final, receipt, check), outcome='already_imported')
                report('registering')
                with (stage / RECEIPT).open('x', encoding='utf-8', newline='\n') as dest:
                    json.dump(receipt, dest, ensure_ascii=False, indent=2)
                    dest.write('\n')
                    dest.flush()
                    os.fsync(dest.fileno())
                check()
                os.rename(stage, final)
                return dict(receipt, outcome='imported')
            finally:
                if job.exists():
                    remove_own_job(control, job)
    except ImportFailure:
        raise
    except (OSError, UnicodeError, ValueError, bofkit.KitError, DiscError) as err:
        raise ImportFailure(str(err)) from err


def main() -> int:
    mp.freeze_support()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--library', type=Path, default=ROOT / 'private' / 'games')
    parser.add_argument('--json', action='store_true', help='Emit the full private import receipt.')
    args = parser.parse_args()
    try:
        result = import_game(args.source, args.library)
        output = result if args.json else {k: result[k] for k in ('outcome', 'library_id', 'serial', 'working_cue', 'reference_match', 'warnings')}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except ImportFailure as err:
        print(f'Import failed: {err}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
