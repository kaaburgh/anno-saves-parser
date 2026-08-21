import io
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

import anno_save_probe as probe


BBDOM_V3_MAGIC = bytes.fromhex("08000000fdffffff")
PAD_BLOCK = 8


def _record_attr(ident, value):
    padding = (-len(value)) % PAD_BLOCK
    return struct.pack("<ii", len(value), ident) + value + (b"\x00" * padding)


def _dictionary(entries):
    ordered = sorted(entries.items())
    ids = b"".join(struct.pack("<H", ident) for ident, _ in ordered)
    names = b"".join(name.encode("utf-8") + b"\x00" for _, name in ordered)
    return struct.pack("<i", len(ordered)) + ids + names


def _meta_blob(timestamp_bytes):
    records = _record_attr(32768, timestamp_bytes)
    tags_off = len(records)
    tags = _dictionary({})
    attrs_off = tags_off + len(tags)
    attrs = _dictionary({32768: "LastModTime"})
    trailer = struct.pack("<ii", tags_off, attrs_off) + BBDOM_V3_MAGIC
    return records + tags + attrs + trailer


class SaveMetaValidationTests(unittest.TestCase):
    def setUp(self):
        probe.SAVE_META_CACHE.clear()

    def test_empty_last_mod_time_falls_back_to_filesystem_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            save = Path(td) / "Autosave 001.a7s"
            save.write_bytes(b"fixture")
            fallback = 1_700_000_123
            os.utime(save, (fallback, fallback))
            progress = probe.Progress(stream=io.StringIO(), interactive=False)
            compressed_meta = zlib.compress(_meta_blob(b""))

            with patch.object(probe, "extract_rda_member", return_value=compressed_meta):
                timestamp, source = probe._save_timestamp(save, progress)

            self.assertEqual(source, "filesystem")
            self.assertEqual(timestamp, float(fallback))
            self.assertIn("LastModTime payload is empty", progress.stream.getvalue())
            self.assertIn("using filesystem mtime", progress.stream.getvalue())

    def test_nonempty_last_mod_time_remains_internal(self):
        with tempfile.TemporaryDirectory() as td:
            save = Path(td) / "Autosave 001.a7s"
            save.write_bytes(b"fixture")
            expected = 1_700_000_456
            compressed_meta = zlib.compress(_meta_blob(expected.to_bytes(8, "little")))

            with patch.object(probe, "extract_rda_member", return_value=compressed_meta):
                meta = probe.read_save_meta(save)

            self.assertEqual(meta["last_mod_time"], expected)


if __name__ == "__main__":
    unittest.main()
