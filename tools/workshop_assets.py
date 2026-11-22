"""Build an offline, private Workshop catalogue from an imported disc."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
from threading import Event
from typing import Callable
import zlib

if __package__:
    from . import bofkit
    from .archive_reader import relative_name
    from .import_games import RECEIPT, ROOT, file_id, no_links
    from .inspect_disc import DiscError, RawDiscReader, inspect_disc
else:
    import bofkit
    from archive_reader import relative_name
    from import_games import RECEIPT, ROOT, file_id, no_links
    from inspect_disc import DiscError, RawDiscReader, inspect_disc


III_GRAPHICS = 'https://github.com/loopyd/bof3-decompilation/blob/66d4fe177324e1ace1d274eb96d77bea8b5b8e18/docs/specs/formats/graphics.md'
IV_GRAPHICS = 'https://github.com/plaught-armor/bof4-recomp/blob/c6ad1cf27a2638870a20571da13db68bc5f7193d/docs/disc-files.md#textures'
MAX_EMI_BYTES = 16 * 1024**2
MAX_TOTAL_EMI = 1024**3
MAX_SECTIONS = 65_536
SCHEMA = 1


class WorkshopError(ValueError):
    """The Workshop retains its input and the previous completed review."""


def sha256(data: bytes | memoryview) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path, check: Callable[[], None]) -> str:
    state = hashlib.sha256()
    with path.open('rb') as stream:
        while part := stream.read(2 * 1024**2):
            check()
            state.update(part)
    return state.hexdigest()


def emi_sections(data: bytes) -> list[dict]:
    """Parse the shared US MATH_TBL header. Each offset is relative to its EMI."""
    if len(data) < 2048 or data[8:16] != b'MATH_TBL':
        raise WorkshopError('Unrecognised EMI header.')
    count, version = struct.unpack_from('<II', data)
    if version != 1 or count > (2048 - 16) // 16:
        raise WorkshopError('Unsupported EMI version or section count.')
    records = []
    offset = 2048
    for slot in range(count):
        size, argument, first_word, type_id = struct.unpack_from('<IIIH', data, 16 + slot * 16)
        if offset + size > len(data):
            raise WorkshopError('An EMI section leaves its container.')
        payload = memoryview(data)[offset:offset + size]
        records.append({'slot': slot, 'offset': offset, 'bytes': size, 'type': type_id, 'argument': argument,
                        'sha256': sha256(payload), 'first_word_matches': (
                            int.from_bytes(payload[:4], 'little') == first_word if size >= 4 else None)})
        offset += (size + 2047) // 2048 * 2048
    return records


def chunk_rows(data: bytes, tiles_across: int) -> tuple[int, int, bytes]:
    """Reassemble 32-word × 32-row upload chunks into contiguous 8-bit index rows."""
    band_bytes = 2048 * tiles_across
    if not 1 <= tiles_across <= 32 or not data or len(data) % band_bytes:
        raise WorkshopError('The texture does not contain complete declared tile rows.')
    width = tiles_across * 64
    height = len(data) // width
    if height > 512:
        raise WorkshopError('The texture exceeds the supported VRAM height.')
    rows = bytearray(len(data))
    for tile in range(len(data) // 2048):
        band, column = divmod(tile, tiles_across)
        for y in range(32):
            dest = (32 * band + y) * width + column * 64
            source = tile * 2048 + y * 64
            rows[dest:dest + 64] = data[source:source + 64]
    return width, height, bytes(rows)


def palette_rgba(data: bytes) -> list[bytes]:
    if len(data) not in (32, 512):
        raise WorkshopError('Expected a complete 16- or 256-word palette.')
    result = []
    for (word,) in struct.iter_unpack('<H', data):
        rgb = [(v * 255 + 15) // 31 for v in (word & 31, word >> 5 & 31, word >> 10 & 31)]
        result.append(bytes([*rgb, 255 if word else 0]))
    return result


def native_png(width: int, height: int, indices: bytes, palette: bytes) -> bytes:
    if not 0 < width <= 2048 or not 0 < height <= 512 or len(indices) != width * height:
        raise WorkshopError('Invalid indexed image dimensions.')
    colours = palette_rgba(palette)
    if max(indices) >= len(colours):
        raise WorkshopError('The selected palette does not contain an image index.')
    # Indexed PNG retains even identical palette entries. STP depends on the original draw state.
    def chunk(kind, content):
        return struct.pack('>I', len(content)) + kind + content + struct.pack('>I', zlib.crc32(kind + content))
    raw = b''.join(b'\x00' + indices[y * width:(y + 1) * width] for y in range(height))
    return b''.join([b'\x89PNG\r\n\x1a\n', chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 3, 0, 0, 0)),
                     chunk(b'PLTE', b''.join(c[:3] for c in colours)), chunk(b'tRNS', bytes(c[3] for c in colours)),
                     chunk(b'IDAT', zlib.compress(raw, 9)), chunk(b'IEND', b'')])


def preview_sources(game: str) -> set[str]:
    return ({'BIN/ETC/DEMO.EMI;1', 'BIN/ETC/SHOP.EMI;1'} if game == 'bof3' else
            {'BIN/WORLD/AREAE030.EMI;1'} if game == 'bof4' else set())


def build_previews(game: str, record: dict, data: bytes, stage: Path) -> list[dict]:
    source_path = record['path']
    if source_path not in preview_sources(game):
        return []
    sections = record['sections']
    images = []

    def section(slot: int, kind: int, argument: int, size: int) -> tuple[dict, bytes]:
        if slot >= len(sections):
            raise WorkshopError('The reference preview section is missing.')
        item = sections[slot]
        if (item['type'], item['argument'], item['bytes']) != (kind, argument, size):
            raise WorkshopError('The reference preview layout differs from the measured EMI.')
        return item, data[item['offset']:item['offset'] + size]

    def add(name, label, width, height, pixels, colours, image_section, palette_section, **evidence):
        generated = native_png(width, height, pixels, colours)
        filename = name + '.png'
        with (stage / filename).open('xb') as stream:
            stream.write(generated)
        images.append(dict(id=name, label=label, file=filename, width=width, height=height,
                           sha256=sha256(generated), source_path=source_path, container_sha256=record['sha256'],
                           image_section=image_section, palette_section=palette_section, **evidence))

    if game == 'bof3' and source_path == 'BIN/ETC/DEMO.EMI;1':
        image, texture = section(6, 3, 0x0A001000, 262144)
        clut, palette_bank = section(7, 0, 0x80034000, 4096)
        stride, _, rows = chunk_rows(texture, 16)
        for panel in range(4):
            pixels = b''.join(rows[y * stride + panel * 256:y * stride + (panel + 1) * 256] for y in range(192))
            start = 1536 + panel * 512
            add(f'title-panel-{panel + 1}', f'Title panel {panel + 1}', 256, 192, pixels,
                palette_bank[start:start + 512], image, clut, palette_offset_in_section=start,
                image_crop=[panel * 256, 0, 256, 192], reference=III_GRAPHICS,
                interpretation='Published static panel and palette binding. Screen composition and fades require runtime comparison.')
    elif game == 'bof3':
        producer, source = section(8, 0, 0x801EEC00, 5268)
        palette = source[0x1268:0x1288]
        for frame, start in enumerate((0x1294, 0x1354, 0x1414)):
            packed = source[start:start + 128]
            pixels = bytes(index for pair in packed for index in (pair & 15, pair >> 4))
            add(f'save-icon-{frame + 1}', f'Memory-card icon frame {frame + 1}', 16, 16, pixels,
                palette, producer, producer, image_offset_in_section=start, palette_offset_in_section=0x1268,
                sequence='save-icon', frame=frame, reference=III_GRAPHICS,
                interpretation='Three frames in the source producer. Animation speed and runtime display require observation.')
    else:
        image, texture = section(5, 3, 0x0A081208, 294912)
        clut, palette_bank = section(6, 0, 0x80036400, 4096)
        width, height, pixels = chunk_rows(texture, 18)
        for row in range(len(palette_bank) // 512):
            start = row * 512
            add(f'areae030-clut-{row}', f'AREAE030 texture with palette {row}', width, height, pixels,
                palette_bank[start:start + 512], image, clut, palette_offset_in_section=start,
                palette_row=row, reference=IV_GRAPHICS,
                interpretation=('Researchers associate palette 2 with the dusk sky. A runtime screen comparison remains open.'
                                if row == 2 else 'Alternative palette from this container, for comparison.'))
    return images


def review_html(catalogue: dict) -> str:
    esc = html.escape
    title = f"Breath of Fire {'III' if catalogue['game'] == 'bof3' else 'IV' if catalogue['game'] == 'bof4' else 'disc'}"
    choices = ''.join(f'<option value="{esc(p["file"])}">{esc(p["label"])}</option>' for p in catalogue['previews'])
    proof = ''.join(f'<li><strong>{esc(p["label"])}</strong> · {p["width"]} × {p["height"]} · '
                    f'<code>{esc(p["source_path"])}</code>, section {p["image_section"]["slot"]}. '
                    f'{esc(p["interpretation"])}</li>' for p in catalogue['previews'])
    viewer = ''
    for index, role in enumerate(('A', 'B')):
        if choices:
            p = catalogue['previews'][min(index, len(catalogue['previews']) - 1)]
            viewer += (f'<section><label>View {role} <select>{choices}</select></label><div class="scroll">'
                       f'<img src="{esc(p["file"])}" alt="{esc(p["label"])}"></div></section>')
    return f'''<!doctype html><html lang="en-GB"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'self' file:; script-src 'unsafe-inline'">
<title>{title} · Workshop review</title><style>
:root{{color-scheme:dark;font:16px/1.55 system-ui;background:#191b1b;color:#edf1e8}}
body{{max-width:98rem;margin:2rem auto;padding:0 1.2rem}}a{{color:#bbdbd0}}label{{display:block}}
select{{max-width:100%;font:inherit;padding:.3em}} main{{display:grid;gap:1rem;grid-template-columns:repeat(auto-fit,minmax(min(26rem,100%),1fr))}}
.scroll{{margin-top:.6rem;overflow:auto;max-height:72vh;border:1px solid #728179;padding:.5rem;background:#262d2b}}
img{{display:block;image-rendering:pixelated}}li{{margin:.4rem 0}}:focus-visible{{outline:3px solid #ffc770}}
</style><h1>{title} Workshop</h1><p>Private disc review · {esc(catalogue['serial'])} · {catalogue['summary']['emi_sections']} container sections.</p>
<p><a href="catalogue.json">Open the source catalogue</a></p>
{('<label>Pixel scale <select id="scale"><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select></label>' if choices else '<p>No revision-specific preview recipe matched this disc.</p>')}
<main>{viewer}</main><h2>Source evidence</h2><ul>{proof}</ul>
<p>Each PNG uses the original palette indices. Zero colour words are transparent. The source draw state controls console blending.</p>
<script>const views=[...document.querySelectorAll('section')];const scale=document.querySelector('#scale');
function draw(view){{const select=view.querySelector('select'),img=view.querySelector('img');img.alt=select.selectedOptions[0].text;if(img.getAttribute('src')!==select.value)img.src=select.value;else if(img.naturalWidth)img.style.width=(img.naturalWidth*Number(scale.value))+'px';}}
views.forEach((view,i)=>{{const select=view.querySelector('select');select.selectedIndex=Math.min(i,select.options.length-1);select.onchange=()=>draw(view);view.querySelector('img').onload=()=>draw(view);draw(view);}});if(scale)scale.onchange=()=>views.forEach(draw);</script></html>'''


def open_imported_disc(game_dir: Path, check: Callable[[], None]) -> tuple[dict, Path, tuple, dict, str | None]:
    """Verify the selected data track, receipt and disc identity before an interpretation."""
    game_dir = Path(game_dir).absolute()
    no_links(game_dir / RECEIPT)
    receipt_path = game_dir / RECEIPT
    if receipt_path.stat().st_size > 1024**2:
        raise WorkshopError('The import receipt is too large.')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if (receipt.get('schema_version') != 1 or receipt.get('library_id') != game_dir.name or
            not re.fullmatch(r'(?:bof[34]|unrecognised)(?:-[a-f0-9]{16})?', game_dir.name) or
            not re.fullmatch('[a-f0-9]{64}', str(receipt.get('content_fingerprint')))):
        raise WorkshopError('Select a registered game with a valid private import receipt.')
    cue = game_dir / relative_name(receipt['working_cue'])
    no_links(cue)
    if cue.stat().st_size > 1024**2 or sha256(cue.read_bytes()) != receipt['working_cue_sha256']:
        raise WorkshopError('The working descriptor differs from its import receipt.')
    track = cue.parent / relative_name(bofkit.parse_cue(cue)['tracks'][0]['file'])
    no_links(track)
    identity = file_id(track)

    expected = next((e for e in receipt['entries'] if game_dir / relative_name(e['path']) == track), None)
    if not expected or identity[2] != expected['bytes'] or hash_file(track, check) != expected['sha256']:
        raise WorkshopError('The first data track differs from its import receipt.')
    disc = inspect_disc(track)
    if disc['executable_sha256'] != receipt['executable_sha256'] or disc['serial_from_system_cnf'] != receipt['serial']:
        raise WorkshopError('Boot identity differs from the import receipt.')
    measured = expected['sha256']
    known = next((g['game'] for g in bofkit.load_inventory(ROOT)
                  if g['disc_inspection']['executable_sha256'] == disc['executable_sha256']
                  and any(e['sha256'] == measured for e in g['entries'])), None)
    return receipt, track, identity, disc, known


def catalogue_game(game_dir: Path, *, cancel: Event | None = None,
                   progress: Callable[[str, int, int], None] | None = None) -> dict:
    """Read one import receipt and return the path and counts of its atomic review."""
    game_dir = Path(game_dir).absolute()

    def check():
        if cancel and cancel.is_set():
            raise WorkshopError('Catalogue cancelled. The previous completed review remains available.')

    receipt, track, identity, disc, known = open_imported_disc(game_dir, check)
    measured = next(e['sha256'] for e in receipt['entries'] if game_dir / relative_name(e['path']) == track)
    fingerprint = receipt['content_fingerprint']
    output_root = game_dir.parent.parent / 'lab' / 'workshop-assets' / game_dir.name
    # An unqualified edition already includes its fingerprint prefix in the library directory.
    revision = f'v{SCHEMA}' if game_dir.name.endswith(fingerprint[:16]) else f'v{SCHEMA}-{fingerprint}'
    final = output_root / revision
    no_links(final)
    if output_root.is_relative_to(game_dir) or game_dir.is_relative_to(output_root):
        raise WorkshopError('The private review output must be separate from original media.')
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.workshop-', dir=output_root) as stage_name:
        stage = Path(stage_name)
        files, previews = [], []
        kinds = Counter()
        hashes = Counter()
        emi_count = section_count = scanned = 0
        table = disc['file_table']
        for n, entry in enumerate(table, start=1):
            check()
            if progress:
                progress('cataloguing', n, len(table))
            record = dict(entry)
            files.append(record)
            if entry['directory'] or not entry['path'].upper().split(';')[0].endswith('.EMI'):
                continue
            size = entry['bytes']
            if size > MAX_EMI_BYTES or scanned + size > MAX_TOTAL_EMI:
                record['inspection'] = 'size limit'
                continue
            scanned += size
            try:
                data = RawDiscReader(track).read_logical(entry['lba'], size)
                record['sha256'] = sha256(data)
                sections = emi_sections(data)
            except (DiscError, WorkshopError) as exc:
                record['inspection'] = str(exc)
                continue
            section_count += len(sections)
            if section_count > MAX_SECTIONS:
                raise WorkshopError('The complete catalogue exceeds the section limit.')
            emi_count += 1
            record.update(inspection='parsed', sections=sections)
            kinds.update(item['type'] for item in sections)
            hashes.update(item['sha256'] for item in sections)
            if known and entry['path'] in preview_sources(known):
                previews.extend(build_previews(known, record, data, stage))
        if identity != file_id(track):
            raise WorkshopError('The source track changed during cataloguing.')
        summary = {'iso_entries': len(table), 'iso_files': sum(not e['directory'] for e in table),
                   'parsed_emi': emi_count, 'emi_sections': section_count, 'distinct_section_digests': len(hashes),
                   'section_type_counts': dict(sorted(kinds.items())), 'preview_count': len(previews),
                   'scanned_logical_bytes': scanned, 'unparsed_emi': sum(
                       1 for e in files if 'inspection' in e and e['inspection'] != 'parsed')}
        catalogue = {'schema_version': SCHEMA, 'classification': 'private original-game derivatives',
                     'game': receipt['game'], 'serial': receipt['serial'], 'content_fingerprint': fingerprint,
                     'data_track_sha256': measured, 'boot_sha256': disc['executable_sha256'], 'summary': summary,
                     'previews': previews, 'entries': files, 'runtime_appearance_reviewed': False}
        (stage / 'catalogue.json').write_text(json.dumps(catalogue, ensure_ascii=False, separators=(',', ':')) + '\n',
                                               encoding='utf-8', newline='\n')
        (stage / 'review.html').write_text(review_html(catalogue), encoding='utf-8', newline='\n')
        check()
        # The nonce directory and the final revision share a filesystem. No previous work is replaced.
        try:
            os.rename(stage, final)
            outcome = 'created'
        except OSError:
            if not final.is_dir():
                raise
            for expected_file in stage.iterdir():
                actual = final / expected_file.name
                no_links(actual)
                if (not actual.is_file() or actual.stat().st_size != expected_file.stat().st_size or
                        hash_file(actual, check) != hash_file(expected_file, check)):
                    raise WorkshopError('The existing review differs. Its files have been retained.')
            outcome = 'already_catalogued'
    return {'outcome': outcome, 'catalogue': str(final / 'catalogue.json'), 'review': str(final / 'review.html'), **summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game_directory', type=Path, help='Game directory containing its private import receipt.')
    args = parser.parse_args()
    try:
        print(json.dumps(catalogue_game(args.game_directory), indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, DiscError, bofkit.KitError) as err:
        print(f'Workshop error: {err}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
