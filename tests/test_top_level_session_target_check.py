from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import top_level_session_target_check as target_check


class TopLevelSessionTargetCheckTests(unittest.TestCase):
    def test_compare_balances_order_and_requires_exact_descriptors(self) -> None:
        calls: list[str] = []
        descriptors = [{"index": 0, "guid": 7, "binary_offset": 16, "binary_size": 8}]

        def reference(*_args, **_kwargs):
            calls.append("reference")
            return [dict(item) for item in descriptors]

        def candidate(*_args, **_kwargs):
            calls.append("candidate")
            return [dict(item) for item in descriptors]

        with mock.patch.object(target_check, "bb_meta", return_value=(64, 80, {}, {})), mock.patch.object(
            target_check, "extract_sessions", side_effect=reference
        ), mock.patch.object(
            target_check, "scan_top_level_sessions_mmap", side_effect=candidate
        ):
            result = target_check.compare_data_bin(Path("unused.bin"), repeats=4)

        self.assertEqual(
            [
                "reference", "candidate",
                "candidate", "reference",
                "reference", "candidate",
                "candidate", "reference",
            ],
            calls,
        )
        self.assertEqual(1, result["descriptor_count"])
        self.assertEqual(4, len(result["reference_seconds"]))
        self.assertEqual(4, len(result["candidate_seconds"]))

    def test_compare_fails_closed_on_descriptor_mismatch(self) -> None:
        with mock.patch.object(target_check, "bb_meta", return_value=(64, 80, {}, {})), mock.patch.object(
            target_check,
            "extract_sessions",
            return_value=[{"index": 0, "binary_offset": 16, "binary_size": 8}],
        ), mock.patch.object(
            target_check,
            "scan_top_level_sessions_mmap",
            return_value=[{"index": 0, "binary_offset": 24, "binary_size": 8}],
        ):
            with self.assertRaisesRegex(ValueError, "differ from buffered reference"):
                target_check.compare_data_bin(Path("unused.bin"), repeats=2)

    def test_compare_rejects_unbalanced_repeat_count(self) -> None:
        for repeats in (0, 1, 3, -2):
            with self.subTest(repeats=repeats):
                with self.assertRaisesRegex(ValueError, "positive even integer"):
                    target_check.compare_data_bin(Path("unused.bin"), repeats=repeats)

    def test_build_report_omits_source_paths_and_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            saves = [root / "Private Autosave 1.a7s", root / "Private Autosave 2.a7s"]
            for index, save in enumerate(saves, 1):
                save.write_bytes(f"private-{index}".encode())

            comparison = {
                "descriptor_count": 2,
                "descriptor_sha256": "a" * 64,
                "reference_seconds": [0.1, 0.2],
                "candidate_seconds": [0.05, 0.06],
            }
            with mock.patch.object(
                target_check,
                "_prepare_data_bin",
                side_effect=lambda _save, work_dir: work_dir / "data.bin",
            ), mock.patch.object(
                target_check, "compare_data_bin", return_value=comparison
            ):
                report = target_check.build_report(saves, repeats=2)

            encoded = json.dumps(report, sort_keys=True)
            self.assertNotIn(str(root), encoded)
            self.assertNotIn("Private Autosave", encoded)
            self.assertEqual(2, len(report["saves"]))
            self.assertEqual(2, report["repeats"])
            for item in report["saves"]:
                self.assertEqual({
                    "source_sha256",
                    "source_size",
                    "descriptor_count",
                    "descriptor_sha256",
                    "reference_seconds",
                    "candidate_seconds",
                }, set(item))

    def test_build_report_requires_two_saves(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            save = Path(temp) / "one.a7s"
            save.write_bytes(b"private")
            with self.assertRaisesRegex(ValueError, "at least two saves"):
                target_check.build_report([save], repeats=2)

    def test_atomic_output_rejects_source_alias_and_replaces_existing_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.a7s"
            source.write_bytes(b"private")
            report_path = root / "report.json"
            report_path.write_text("stale", encoding="utf-8")
            report = {"schema": "test", "schema_version": 1}

            with self.assertRaisesRegex(ValueError, "aliases a source save"):
                target_check._write_report_atomic(report, source, [source])
            self.assertEqual(b"private", source.read_bytes())

            target_check._write_report_atomic(report, report_path, [source])
            self.assertEqual(report, json.loads(report_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
