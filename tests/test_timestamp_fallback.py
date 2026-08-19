import io
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import anno_save_probe as probe


class TimestampFallbackTests(unittest.TestCase):
    def setUp(self):
        probe.SAVE_META_CACHE.clear()

    def test_discovery_reports_expected_metadata_fallback_once_across_date_selection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save = root / "Autosave 001.a7s"
            save.write_bytes(b"fixture")
            fallback = datetime(2026, 8, 15, 12, 0).timestamp()
            os.utime(save, (fallback, fallback))
            stream = io.StringIO()
            progress = probe.Progress(stream=stream, interactive=False)

            with patch.object(probe, "cached_save_meta", side_effect=ValueError("bad metadata")):
                saves = probe.discover_saves([root], progress)
                selected = probe.select_from(saves, "2026-08-15", progress)

            self.assertEqual(selected, [save])
            output = stream.getvalue()
            self.assertEqual(output.count("using filesystem mtime"), 1)
            self.assertIn("Autosave 001.a7s", output)
            self.assertIn("ValueError: bad metadata", output)

    def test_missing_internal_timestamp_reports_filesystem_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save = root / "Autosave 001.a7s"
            save.write_bytes(b"fixture")
            stream = io.StringIO()
            progress = probe.Progress(stream=stream, interactive=False)

            with patch.object(probe, "cached_save_meta", return_value={}):
                found = probe.discover_saves([root], progress)

            self.assertEqual(found, [save])
            self.assertIn("LastModTime missing", stream.getvalue())
            self.assertIn("using filesystem mtime", stream.getvalue())

    def test_discovery_does_not_swallow_unexpected_metadata_exception(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Autosave 001.a7s").write_bytes(b"fixture")

            with patch.object(probe, "cached_save_meta", side_effect=RuntimeError("bug")):
                with self.assertRaisesRegex(RuntimeError, "bug"):
                    probe.discover_saves([root])

    def test_date_selection_does_not_swallow_unexpected_metadata_exception(self):
        save = Path("Autosave 001.a7s")
        with patch.object(probe, "cached_save_meta", side_effect=RuntimeError("bug")):
            with self.assertRaisesRegex(RuntimeError, "bug"):
                probe.select_from([save], "2026-08-15")


if __name__ == "__main__":
    unittest.main()
