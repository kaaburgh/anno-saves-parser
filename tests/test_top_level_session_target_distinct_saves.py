from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import top_level_session_target_check as target_check


class TopLevelSessionTargetDistinctSaveTests(unittest.TestCase):
    def test_build_report_rejects_duplicate_resolved_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "one.a7s"
            source.write_bytes(b"private-one")

            with self.assertRaisesRegex(ValueError, "distinct save paths"):
                target_check.build_report([source, source], repeats=2)

    def test_build_report_rejects_duplicate_save_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            saves = [root / "one.a7s", root / "two.a7s"]
            for save in saves:
                save.write_bytes(b"same-private-save")

            with mock.patch.object(
                target_check,
                "_prepare_data_bin",
                side_effect=lambda _save, work_dir: work_dir / "data.bin",
            ), mock.patch.object(
                target_check,
                "compare_data_bin",
                return_value={
                    "descriptor_count": 0,
                    "descriptor_sha256": "a" * 64,
                    "reference_seconds": [0.1, 0.2],
                    "candidate_seconds": [0.05, 0.06],
                },
            ):
                with self.assertRaisesRegex(ValueError, "distinct save contents"):
                    target_check.build_report(saves, repeats=2)


if __name__ == "__main__":
    unittest.main()
