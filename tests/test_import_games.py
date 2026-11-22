import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
from threading import Event
import unittest
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from tools.archive_reader import ImportFailure, Limits, Member, check_members, format_of, relative_name
from tools.import_games import RECEIPT, STAGING_MARK, import_game


def synthetic_bin() -> bytes:
    sectors = [bytearray(2352) for _ in range(26)]
    for sector in sectors:
        sector[:12] = b'\x00' + b'\xff' * 10 + b'\x00'
        sector[15] = 2

    def record(name, lba, length, is_dir=False):
        name = name if isinstance(name, bytes) else name.encode()
        data = bytearray(33 + len(name) + (len(name) % 2 == 0))
        data[0] = len(data)
        data[2:10] = struct.pack('<I', lba) + struct.pack('>I', lba)
        data[10:18] = struct.pack('<I', length) + struct.pack('>I', length)
        data[25] = 2 if is_dir else 0
        data[28:32] = b'\x01\x00\x00\x01'
        data[32] = len(name)
        data[33:33 + len(name)] = name
        return data

    def payload(lba, data):
        sectors[lba][24:24 + len(data)] = data

    pvd = bytearray(2048)
    pvd[:7] = b'\x01CD001\x01'
    pvd[40:72] = b'BREATH_OF_FIRE3'.ljust(32)
    pvd[80:84] = struct.pack('<I', len(sectors))
    pvd[156:190] = record(b'\0', 18, 2048, True)
    payload(16, pvd)
    cnf = b'BOOT = cdrom:\\SLUS_004.22;1\r\n'
    exe = b'PS-X EXE' + bytes(99)
    table = record('SYSTEM.CNF;1', 20, len(cnf)) + record('SLUS_004.22;1', 21, len(exe))
    payload(18, table)
    payload(20, cnf)
    payload(21, exe)
    return b''.join(sectors)


CUE = b'FILE "game.bin" BINARY\r\n TRACK 01 MODE2/2352\r\n INDEX 01 00:00:00\r\n'


class ImportCases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.library = self.base / 'library'
        self.raw = synthetic_bin()
        self.selected = self.base / 'My disc'
        self.selected.mkdir()
        self.cue = self.selected / 'game.cue'
        self.cue.write_bytes(CUE)
        (self.selected / 'game.bin').write_bytes(self.raw)

    def make_zip(self, names=None):
        path = self.base / 'wrong.suffix'
        with ZipFile(path, 'w', ZIP_STORED) as z:
            for name, data in names if names is not None else [('café/game.bin', self.raw), ('café/game.cue', CUE)]:
                z.writestr(name, data)
        return path

    def test_unknown_revision_is_original_only(self):
        receipt = import_game(self.cue, self.library)
        self.assertEqual(receipt['serial'], 'SLUS-00422')
        self.assertTrue(receipt['original_play_candidate'])
        self.assertFalse(receipt['reference_match'] or receipt['verified_patches_enabled'] or receipt['gameplay_validated'])
        self.assertTrue(receipt['library_id'].startswith('bof3-'))
        self.assertEqual((self.library / receipt['library_id'] / 'game.bin').read_bytes(), self.raw)

    def test_zip_signature_unicode_and_cross_source_idempotence(self):
        archive = self.make_zip()
        receipt = import_game(archive, self.library)
        self.assertEqual(receipt['input_format'], 'zip')
        self.assertEqual(receipt['archive']['sha256'], hashlib.sha256(archive.read_bytes()).hexdigest())
        reused = import_game(self.cue, self.library)
        self.assertEqual(reused['outcome'], 'already_imported')
        self.assertEqual(reused['content_fingerprint'], receipt['content_fingerprint'])
        self.assertEqual(len(list(self.library.glob('*/' + RECEIPT))), 1)

    def test_misnamed_7zip(self):
        path = self.base / 'original.zip'
        try:
            result = subprocess.run(['tar', '--format=7zip', '-cf', str(path), 'game.bin', 'game.cue'],
                                    cwd=self.selected, capture_output=True, timeout=10)
        except FileNotFoundError:
            self.skipTest('No local bsdtar for the synthetic 7-Zip fixture.')
        if result.returncode:
            self.skipTest('The local tar does not support writing 7-Zip test archives.')
        self.assertEqual(format_of(path.read_bytes()[:8]), '7z')
        receipt = import_game(path, self.library, limits=replace(Limits(), ratio=1000))
        self.assertEqual(receipt['input_format'], '7z')

    def test_paths_aliases_and_payloads_rejected_before_activation(self):
        for bad in ('../escape.bin', '/absolute.bin', 'C:/drive.bin', 'AUX.cue', 'dir /x.bin', 'disc.bin:alt', '.git/x.bin', 'safe/../x.bin'):
            with self.subTest(bad=bad), self.assertRaises(ImportFailure):
                relative_name(bad)
        for conflict in ([Member('Data/One.bin', 2352), Member('data/Two.bin', 2352)],
                         [Member('é.bin', 2352), Member('e\u0301.bin', 2352)],
                         [Member('game.cue', 5), Member('game.cue', 5)],
                         [Member('game.bin', 2352), Member('game.bin/child.cue', 10)]):
            with self.subTest(conflict=conflict), self.assertRaises(ImportFailure):
                check_members(conflict, None, self.base, Limits())
        for bad in ('../escape.bin', 'run.exe', 'nested.zip'):
            source = self.make_zip([('game.cue', CUE), ('game.bin', self.raw), (bad, self.raw)])
            with self.subTest(name=bad), self.assertRaises(ImportFailure):
                import_game(source, self.library)
        self.assertFalse((self.base / 'escape.bin').exists())
        self.assertFalse(list(self.library.glob('*/' + RECEIPT)))

    def test_links_are_never_extracted(self):
        link = ZipInfo('game.bin')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        source = self.make_zip([('game.cue', CUE), (link, b'target')])
        with self.assertRaises(ImportFailure):
            import_game(source, self.library)
        self.assertFalse(list(self.library.glob('*/' + RECEIPT)))

    def test_unreferenced_or_disguised_executable_is_rejected(self):
        for name, data in [('extra.bin', self.raw), ('extra.bin', b'MZ' + bytes(2350))]:
            source = self.make_zip([('game.cue', CUE), ('game.bin', self.raw), (name, data)])
            with self.subTest(prefix=data[:2]), self.assertRaises(ImportFailure):
                import_game(source, self.library)
        self.assertFalse(list(self.library.glob('*/' + RECEIPT)))

    def test_corrupt_zip_and_bad_sector(self):
        source = self.make_zip()
        binary = bytearray(source.read_bytes())
        at = binary.index(self.raw[:22])
        binary[at + 3] ^= 1
        source.write_bytes(binary)
        with self.assertRaises(ImportFailure):
            import_game(source, self.library)
        (self.selected / 'game.bin').write_bytes(bytes(len(self.raw)))
        with self.assertRaises(ImportFailure):
            import_game(self.cue, self.library)

    def test_limits_cancel_failure_and_retry_leave_one_complete_game(self):
        for limits in (replace(Limits(), reserve_bytes=2**60), replace(Limits(), total_bytes=10), replace(Limits(), seconds=0)):
            with self.subTest(limits=limits), self.assertRaises(ImportFailure):
                import_game(self.cue, self.library, limits=limits)
        source = self.make_zip()
        stop = Event()

        def cancel_during_copy(phase, done, total):
            if phase == 'copying' and done:
                stop.set()

        with self.assertRaisesRegex(ImportFailure, 'cancelled'):
            import_game(source, self.library, cancel=stop, progress=cancel_during_copy)
        self.assertFalse(list(self.library.glob('*/' + RECEIPT)))
        self.assertFalse(list((self.library / '.atelier-import').glob('job-*')))
        self.assertEqual(import_game(source, self.library)['outcome'], 'imported')

    def test_interrupted_stage_recovery_and_existing_corruption(self):
        abandoned = self.library / '.atelier-import' / ('job-' + 'a' * 32)
        abandoned.mkdir(parents=True)
        (abandoned / 'owner').write_bytes(STAGING_MARK)
        (abandoned / 'partial.bin').write_bytes(b'incomplete')
        receipt = import_game(self.cue, self.library)
        self.assertFalse(abandoned.exists())
        dest = self.library / receipt['library_id'] / 'game.bin'
        dest.write_bytes(b'damaged')
        with self.assertRaisesRegex(ImportFailure, 'preserved'):
            import_game(self.cue, self.library)
        self.assertEqual(dest.read_bytes(), b'damaged')

    def test_concurrent_copies_register_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(import_game, self.cue, self.library) for _ in range(2)]
            outcomes = sorted(f.result()['outcome'] for f in futures)
        self.assertEqual(outcomes, ['already_imported', 'imported'])

    def test_confused_identity_in_stored_receipt_is_rejected(self):
        result = import_game(self.cue, self.library)
        receipt = self.library / result['library_id'] / RECEIPT
        doc = json.loads(receipt.read_text(encoding='utf-8'))
        doc['verified_patches_enabled'] = True
        receipt.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaises(ImportFailure):
            import_game(self.cue, self.library)

    def test_missing_and_malformed_cues(self):
        for data in (CUE.replace(b'game.bin', b'Game.bin'), CUE.replace(b'game.bin', b'../game.bin'),
                     CUE.replace(b'00:00:00', b'00:01:00'), CUE + b' INDEX 00 00:00:00\n'):
            self.cue.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(ImportFailure):
                import_game(self.cue, self.library)


if __name__ == '__main__':
    unittest.main()
