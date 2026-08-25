from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import anno_save_probe as probe


class ProductionTopLevelSessionScanTests(unittest.TestCase):
    def test_extract_sessions_delegates_to_mmap_scanner(self) -> None:
        tags = {1: "#1", 2: "GameSessions"}
        attrs = {32768: "BinaryData"}
        expected = [{"index": 0, "binary_offset": 32, "binary_size": 16}]
        progress = object()

        with tempfile.TemporaryDirectory() as td:
            data_bin = Path(td) / "data.bin"
            data_bin.write_bytes(b"placeholder")
            with (
                mock.patch.object(probe, "bb_meta", return_value=(123, 456, tags, attrs)),
                mock.patch.object(
                    probe,
                    "scan_top_level_sessions_mmap",
                    return_value=expected,
                ) as scanner,
            ):
                actual = probe.extract_sessions(data_bin, Path(td) / "unused", progress)

        self.assertEqual(actual, expected)
        scanner.assert_called_once_with(data_bin, 123, tags, attrs, progress)


if __name__ == "__main__":
    unittest.main()
