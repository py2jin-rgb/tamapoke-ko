"""Regression checks for corrupt downloads and unsafe flash maps."""
from pathlib import Path
import tempfile
import unittest

from package_release import check_bytes, digest, install_manifest, install_dual_slot_manifest, safe_path


class ReleaseIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.data = b'verified firmware fixture'
        self.entry = {'firmware_path': 'firmware/fixture.bin', 'size': len(self.data), 'sha256': digest(self.data)}

    def test_download_truncation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Size mismatch'):
            check_bytes(self.data[:-1], self.entry)

    def test_same_size_corruption_is_rejected(self):
        changed = bytes([self.data[0] ^ 1]) + self.data[1:]
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            check_bytes(changed, self.entry)

    def test_verified_bytes_are_preserved_exactly(self):
        self.assertEqual(check_bytes(self.data, self.entry), self.data)

    def test_manifest_never_includes_bootloader_nvs_or_otadata(self):
        for offset in (0x10000, 0x310000):
            m = install_manifest('Fixture', '2.8', 'firmware/fixture.bin', offset)
            self.assertIs(m['new_install_prompt_erase'], True)
            self.assertEqual(m['builds'], [{'chipFamily': 'ESP32-S3', 'parts': [{'path': 'firmware/fixture.bin', 'offset': offset}]}])

    def test_dual_slot_usb_writes_same_app_and_keeps_erase_prompt(self):
        m = install_dual_slot_manifest('Fixture USB', '2.8', 'firmware/fixture.bin',
                                       0x10000, 0x310000,
                                       {'sha256': self.entry['sha256'], 'size': self.entry['size']})
        self.assertIs(m['new_install_prompt_erase'], True)
        self.assertEqual(m['builds'], [{'chipFamily': 'ESP32-S3', 'parts': [
            {'path': 'firmware/fixture.bin', 'offset': 0x10000},
            {'path': 'firmware/fixture.bin', 'offset': 0x310000}
        ]}])
        self.assertEqual(m['sha256'], self.entry['sha256'])
        with self.assertRaisesRegex(ValueError, 'Invalid OTA'):
            install_dual_slot_manifest('Fixture', '2.8', 'firmware/fixture.bin', 0x310000, 0x10000)

    def test_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('../../source.ino', '/tmp/firmware.bin', 'firmware/../../source.ino'):
                with self.assertRaises(ValueError):
                    safe_path(Path(d), name)
            self.assertEqual(safe_path(Path(d), 'firmware/fixture.bin'), Path(d) / 'firmware/fixture.bin')


if __name__ == '__main__':
    unittest.main()
