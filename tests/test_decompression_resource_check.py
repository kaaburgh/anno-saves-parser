import json
import tempfile
import unittest
from pathlib import Path

import decompression_resource_check as resource_check


class DecompressionResourceCheckTests(unittest.TestCase):
    def _source_pair(self, root: Path) -> list[Path]:
        first = root / "private-first.a7s"
        second = root / "private-second.a7s"
        first.write_bytes(b"synthetic-save-one")
        second.write_bytes(b"synthetic-save-two")
        return [first, second]

    def test_linux_smaps_rollup_parser_returns_pss_bytes(self):
        text = """Rss:               1234 kB\nPss:                321 kB\nPrivate_Clean:        10 kB\n"""
        self.assertEqual(resource_check._parse_linux_smaps_rollup(text), 321 * 1024)

    def test_build_report_balances_chunk_order_for_workers_one_and_two(self):
        calls = []

        def fake_run_batch(snapshots, chunk_bytes, workers):
            calls.append((workers, chunk_bytes))
            digests = [
                resource_check.hashlib.sha256(snapshot.read_bytes()).hexdigest()
                for snapshot in snapshots
            ]
            return {
                "canonical_sha256": digests,
                "elapsed_seconds": float(workers) + chunk_bytes / 10_000_000,
                "peak_memory_bytes": workers * 1000 + chunk_bytes,
                "memory_metric": "pss",
            }

        with tempfile.TemporaryDirectory() as td:
            saves = self._source_pair(Path(td))
            report = resource_check.build_report(
                saves,
                repeats=2,
                run_batch_fn=fake_run_batch,
            )

        ref = resource_check.REFERENCE_CHUNK_BYTES
        candidate = resource_check.DEFAULT_DECOMPRESSION_CHUNK_BYTES
        self.assertEqual(
            calls,
            [
                (1, ref),
                (1, candidate),
                (1, candidate),
                (1, ref),
                (2, ref),
                (2, candidate),
                (2, candidate),
                (2, ref),
            ],
        )
        self.assertEqual(report["worker_counts"], [1, 2])
        self.assertEqual(report["memory_metric"], "pss")
        self.assertEqual(len(report["inputs"]), 2)
        self.assertNotIn("private-first", json.dumps(report))
        self.assertNotIn("private-second", json.dumps(report))
        for result in report["results"]:
            self.assertEqual(
                result["reference"]["canonical_sha256"],
                result["candidate"]["canonical_sha256"],
            )
            self.assertEqual(len(result["reference"]["peak_memory_bytes"]), 2)
            self.assertEqual(len(result["candidate"]["peak_memory_bytes"]), 2)

    def test_build_report_rejects_reference_candidate_digest_mismatch(self):
        def mismatching_run_batch(snapshots, chunk_bytes, workers):
            marker = "candidate" if chunk_bytes == resource_check.DEFAULT_DECOMPRESSION_CHUNK_BYTES else "reference"
            return {
                "canonical_sha256": [marker for _ in snapshots],
                "elapsed_seconds": 1.0,
                "peak_memory_bytes": 1024,
                "memory_metric": "pss",
            }

        with tempfile.TemporaryDirectory() as td:
            saves = self._source_pair(Path(td))
            with self.assertRaisesRegex(
                RuntimeError,
                "canonical state differs between reference and candidate resource runs",
            ):
                resource_check.build_report(
                    saves,
                    repeats=2,
                    run_batch_fn=mismatching_run_batch,
                )

    def test_build_report_requires_two_distinct_save_contents(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / "one.a7s"
            second = root / "two.a7s"
            first.write_bytes(b"same")
            second.write_bytes(b"same")
            with self.assertRaisesRegex(ValueError, "source save contents must be distinct"):
                resource_check.build_report(
                    [first, second],
                    repeats=2,
                    run_batch_fn=lambda *_args: None,
                )

    def test_build_report_requires_at_least_two_saves(self):
        with tempfile.TemporaryDirectory() as td:
            save = Path(td) / "one.a7s"
            save.write_bytes(b"one")
            with self.assertRaisesRegex(ValueError, "at least two distinct source saves"):
                resource_check.build_report(
                    [save],
                    repeats=2,
                    run_batch_fn=lambda *_args: None,
                )

    def test_validate_output_path_rejects_source_alias(self):
        with tempfile.TemporaryDirectory() as td:
            save = Path(td) / "source.a7s"
            save.write_bytes(b"source")
            with self.assertRaisesRegex(ValueError, "output path must not alias a source save"):
                resource_check.validate_output_path(save, [save])

    def test_decode_worker_stdout_uses_last_nonempty_json_line(self):
        value = resource_check._decode_worker_stdout(
            "diagnostic line\n{\"canonical_sha256\": \"abc\", \"elapsed_seconds\": 1.25}\n"
        )
        self.assertEqual(value["canonical_sha256"], "abc")
        self.assertEqual(value["elapsed_seconds"], 1.25)

    def test_repeat_validation_requires_positive_even_count(self):
        for repeats in (0, 1, 3, -2):
            with self.subTest(repeats=repeats):
                with self.assertRaisesRegex(ValueError, "positive even"):
                    resource_check._validate_repeats(repeats)


if __name__ == "__main__":
    unittest.main()
