import struct
import tempfile
import unittest
from pathlib import Path

import anno_save_probe as probe


def _write_filedb(path: Path, data: bytes, tags_off: int, attrs_off: int) -> None:
    trailer = struct.pack("<ii", tags_off, attrs_off) + probe.BBDOM_V3_MAGIC
    path.write_bytes(data + trailer)


class TopLevelFileDBBoundsTests(unittest.TestCase):
    def test_empty_top_level_dictionaries_are_accepted(self):
        data = struct.pack("<i", 0) + struct.pack("<i", 0)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "empty.bin"
            _write_filedb(path, data, 0, 4)

            tags_off, attrs_off, tags, attrs = probe.bb_meta(path)

        self.assertEqual((tags_off, attrs_off), (0, 4))
        self.assertEqual(tags, {})
        self.assertEqual(attrs, {})

    def test_negative_top_level_dictionary_count_is_rejected(self):
        data = struct.pack("<i", -1) + struct.pack("<i", 0)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "negative-count.bin"
            _write_filedb(path, data, 0, 4)

            with self.assertRaisesRegex(ValueError, "negative dictionary entry count"):
                probe.bb_meta(path)

    def test_oversized_top_level_dictionary_count_cannot_read_past_data_region(self):
        data = struct.pack("<i", 1_000_000) + struct.pack("<i", 0)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "oversized-count.bin"
            _write_filedb(path, data, 0, 4)

            with self.assertRaisesRegex(ValueError, "dictionary exceeds FileDB slice"):
                probe.bb_meta(path)

    def test_top_level_dictionary_offset_must_precede_trailer(self):
        data = struct.pack("<i", 0) + struct.pack("<i", 0)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad-offset.bin"
            _write_filedb(path, data, len(data), 4)

            with self.assertRaisesRegex(ValueError, "dictionary offset outside file"):
                probe.bb_meta(path)

    def test_unterminated_top_level_dictionary_string_is_rejected(self):
        data = struct.pack("<iH", 1, 7) + b"unterminated"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "unterminated.bin"
            _write_filedb(path, data, 0, 0)

            with self.assertRaisesRegex(ValueError, "dictionary string exceeds FileDB slice"):
                probe.bb_meta(path)

    def test_top_level_filedb_requires_complete_trailer(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "short.bin"
            path.write_bytes(b"short")

            with self.assertRaisesRegex(ValueError, "truncated FileDB trailer"):
                probe.bb_meta(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
