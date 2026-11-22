#!/usr/bin/env python3
"""Read-only bounded inspection of raw 2352-byte PlayStation data tracks.

Reports ISO9660 structure, SYSTEM.CNF and a boot-executable digest. Does not dump
assets, alter files, verify all sector checksums, or establish game compatibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

RAW_SECTOR_BYTES = 2352
LOGICAL_SECTOR_BYTES = 2048
MAX_DIRECTORY_BYTES = 8 * 1024 * 1024
MAX_READ_BYTES = 32 * 1024 * 1024
MAX_TOTAL_READ_BYTES = 128 * 1024 * 1024


class DiscError(RuntimeError):
    """A bounded parsing failure; the input is never repaired automatically."""


class RawDiscReader:
    def __init__(self, path: Path):
        self.path = path
        size = path.stat().st_size
        if not path.is_file() or size % RAW_SECTOR_BYTES:
            raise DiscError('Expected a sector-aligned raw 2352-byte data track.')
        self.sector_count = size // RAW_SECTOR_BYTES
        self.total_read_bytes = 0

    def read_logical(self, first_sector: int, byte_count: int) -> bytes:
        if first_sector < 0 or byte_count < 0 or byte_count > MAX_READ_BYTES:
            raise DiscError('Logical read exceeds the permitted bounds.')
        sectors_needed = (byte_count + LOGICAL_SECTOR_BYTES - 1) // LOGICAL_SECTOR_BYTES
        if first_sector + sectors_needed > self.sector_count:
            raise DiscError('Logical extent leaves the supplied data track.')
        self.total_read_bytes += sectors_needed * RAW_SECTOR_BYTES
        if self.total_read_bytes > MAX_TOTAL_READ_BYTES:
            raise DiscError('Inspection read budget exceeded.')
        result = bytearray()
        with self.path.open('rb') as source:
            source.seek(first_sector * RAW_SECTOR_BYTES)
            for _ in range(sectors_needed):
                sector = source.read(RAW_SECTOR_BYTES)
                if len(sector) != RAW_SECTOR_BYTES or sector[:12] != b'\x00' + b'\xff' * 10 + b'\x00':
                    raise DiscError('Missing raw data-sector sync header.')
                mode = sector[15]
                if mode == 1:
                    offset = 16
                elif mode == 2:
                    if sector[16:20] != sector[20:24] or sector[18] & 0x20:
                        raise DiscError('Expected repeated Mode-2 Form-1 subheaders for filesystem data.')
                    offset = 24
                else:
                    raise DiscError('Unsupported data-sector mode.')
                result.extend(sector[offset:offset + LOGICAL_SECTOR_BYTES])
        return bytes(result[:byte_count])

    def directory_entries(self, first_sector: int, byte_count: int) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        visited: set[tuple[int, int]] = set()

        def walk(sector: int, length: int, prefix: str, depth: int) -> None:
            if depth > 12 or length > MAX_DIRECTORY_BYTES or (sector, length) in visited:
                raise DiscError('Directory recursion, cycle or size limit exceeded.')
            visited.add((sector, length))
            data = self.read_logical(sector, length)
            offset = 0
            while offset < len(data):
                record_length = data[offset]
                if record_length == 0:
                    offset = (offset // LOGICAL_SECTOR_BYTES + 1) * LOGICAL_SECTOR_BYTES
                    continue
                record = data[offset:offset + record_length]
                offset += record_length
                if len(record) != record_length or record_length < 34 or 33 + record[32] > record_length:
                    raise DiscError('Invalid ISO9660 directory record.')
                raw_name = record[33:33 + record[32]]
                if raw_name in (b'\x00', b'\x01'):
                    continue
                name = raw_name.decode('ascii', errors='replace')
                first = int.from_bytes(record[2:6], 'little')
                size = int.from_bytes(record[10:14], 'little')
                if first + (size + 2047) // 2048 > self.sector_count:
                    raise DiscError('A filesystem entry exceeds the supplied data track.')
                entry = {'path': prefix + name, 'lba': first, 'bytes': size, 'directory': bool(record[25] & 2)}
                entries.append(entry)
                if len(entries) > 100_000:
                    raise DiscError('Directory entry limit exceeded.')
                if entry['directory']:
                    walk(first, size, prefix + name + '/', depth + 1)
        walk(first_sector, byte_count, '', 0)
        return entries


def inspect_disc(path: Path) -> dict[str, Any]:
    reader = RawDiscReader(path)
    descriptor = reader.read_logical(16, LOGICAL_SECTOR_BYTES)
    if descriptor[:7] != b'\x01CD001\x01':
        raise DiscError('No expected ISO9660 primary volume descriptor at sector 16.')
    root_record = descriptor[156:190]
    files = reader.directory_entries(int.from_bytes(root_record[2:6], 'little'),
                                     int.from_bytes(root_record[10:14], 'little'))
    system_entry = next((entry for entry in files if entry['path'].upper().split(';')[0] == 'SYSTEM.CNF'), None)
    if system_entry is None or system_entry['bytes'] > 64 * 1024:
        raise DiscError('Missing or unexpectedly large SYSTEM.CNF.')
    system_text = reader.read_logical(system_entry['lba'], system_entry['bytes']).decode('ascii', errors='replace')
    serial_match = re.search(r'(S[LCP][A-Z]{2})[_-](\d{3})\.(\d{2})', system_text, re.I)
    serial = f'{serial_match[1].upper()}-{serial_match[2]}{serial_match[3]}' if serial_match else None
    executable_entry = next((entry for entry in files if serial and
                             entry['path'].split(';')[0].replace('_', '-').replace('.', '').upper() == serial), None)
    if executable_entry is None:
        raise DiscError('Could not resolve the boot executable from SYSTEM.CNF.')
    executable = reader.read_logical(executable_entry['lba'], executable_entry['bytes'])
    if executable[:8] != b'PS-X EXE':
        raise DiscError('Boot file lacks the expected PS-X EXE signature.')
    return {
        'file': path.name, 'raw_sector_count': reader.sector_count,
        'iso9660_volume': descriptor[40:72].decode('ascii', errors='replace').strip(),
        'pvd_declared_logical_blocks': int.from_bytes(descriptor[80:84], 'little'),
        'system_cnf': system_text, 'serial_from_system_cnf': serial,
        'boot_executable': executable_entry['path'], 'executable_bytes': len(executable),
        'executable_sha256': hashlib.sha256(executable).hexdigest(),
        'executable_header': executable[:8].decode('ascii'),
        'root_entry_count': sum('/' not in entry['path'] for entry in files),
        'total_entries': len(files), 'all_enumerated_extents_within_track': True,
        'file_table': files, 'gameplay_tested': False, 'sector_edc_ecc_scan': False,
        'limitations': 'Filesystem/identity checks only; no assets extracted, fixes applied or runtime boot performed.',
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('track', type=Path, help='The raw BIN containing the first data track; never the audio track.')
    arguments = parser.parse_args()
    try:
        print(json.dumps(inspect_disc(arguments.track), indent=2))
        return 0
    except (OSError, ValueError, DiscError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
