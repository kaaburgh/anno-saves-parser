import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import canonical_sort_target_check as target_check


class CanonicalSortTargetCheckTests(unittest.TestCase):
    @staticmethod
    def _session(guid, session_id, map_name, marker):
        return {
            "session_guid": guid,
            "session_id": session_id,
            "map": map_name,
            "player_areas": [{"area_id": marker, "owner_id": 0}],
            "buildings": [],
        }

    def test_projected_sessions_match_eager_reference_with_balanced_order(self):
        sessions = [
            self._session(300, 3, "C", 3),
            self._session(100, 1, "A", 1),
            self._session(200, 2, "B", 2),
        ]
        calls = []
        original = target_check._timed_sort

        def recording(sorter, items):
            calls.append(sorter.__name__)
            return original(sorter, items)

        with patch.object(target_check, "_timed_sort", side_effect=recording):
            result = target_check.compare_projected_sessions(sessions, repeats=4)

        self.assertEqual(result["session_count"], 3)
        self.assertEqual(len(result["reference_ordering_seconds"]), 4)
        self.assertEqual(len(result["candidate_ordering_seconds"]), 4)
        self.assertEqual(
            calls,
            [
                "reference", "candidate",
                "candidate", "reference",
                "reference", "candidate",
                "candidate", "reference",
            ],
        )

    def test_primary_ties_preserve_full_state_tiebreaker(self):
        sessions = [
            self._session(100, 1, "A", 9),
            self._session(100, 1, "A", 2),
            self._session(100, 1, "A", 5),
        ]
        result = target_check.compare_projected_sessions(sessions, repeats=2)
        expected = sorted(sessions, key=target_check._eager_reference_key)
        self.assertEqual(target_check.sort_canonical_sessions(sessions), expected)
        self.assertEqual(
            result["canonical_sha256"],
            target_check._canonical_digest(
                target_check._canonical_state_from_sessions(expected)
            ),
        )

    def test_repeats_must_be_positive_and_even(self):
        for repeats in (0, 1, 3, -2):
            with self.subTest(repeats=repeats):
                with self.assertRaisesRegex(ValueError, "positive even"):
                    target_check.compare_projected_sessions([], repeats=repeats)

    def test_build_report_requires_two_saves(self):
        with self.assertRaisesRegex(ValueError, "at least two saves"):
            target_check.build_report([], repeats=2)

    def test_build_report_rejects_duplicate_resolved_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            save = Path(temp) / "same.a7s"
            save.write_bytes(b"same-save")
            with self.assertRaisesRegex(ValueError, "distinct save paths"):
                target_check.build_report([save, save], repeats=2)

    def test_build_report_rejects_duplicate_save_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            saves = [root / "one.a7s", root / "two.a7s"]
            for save in saves:
                save.write_bytes(b"identical-save-bytes")

            comparison = {
                "session_count": 1,
                "canonical_sha256": "a" * 64,
                "reference_ordering_seconds": [0.1, 0.1],
                "candidate_ordering_seconds": [0.1, 0.1],
            }
            with patch.object(
                target_check, "_prepare_raw_sessions", return_value=[{"raw": True}]
            ), patch.object(target_check, "compare_raw_sessions", return_value=comparison):
                with self.assertRaisesRegex(ValueError, "distinct save contents"):
                    target_check.build_report(saves, repeats=2)

    def test_report_projection_omits_source_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            saves = [root / "private-one.a7s", root / "private-two.a7s"]
            for index, save in enumerate(saves, 1):
                save.write_bytes(f"save-{index}".encode("ascii"))

            comparison = {
                "session_count": 2,
                "canonical_sha256": "a" * 64,
                "reference_ordering_seconds": [0.2, 0.1],
                "candidate_ordering_seconds": [0.1, 0.05],
            }

            def fake_snapshot(source, work_dir):
                snapshot = work_dir / "source.a7s"
                snapshot.write_bytes(source.read_bytes())
                return snapshot, target_check._sha256_file(snapshot), snapshot.stat().st_size

            with patch.object(target_check, "_copy_verified_snapshot", side_effect=fake_snapshot), patch.object(
                target_check, "_prepare_raw_sessions", return_value=[{"raw": True}]
            ), patch.object(target_check, "compare_raw_sessions", return_value=comparison):
                report = target_check.build_report(saves, repeats=2)

            encoded = json.dumps(report, sort_keys=True)
            self.assertNotIn("private-one.a7s", encoded)
            self.assertNotIn("private-two.a7s", encoded)
            self.assertNotIn(str(root), encoded)
            self.assertEqual(len(report["saves"]), 2)
            self.assertEqual(report["timing_order"], "balanced alternating eager/lazy ordering pairs")

    def test_output_may_not_alias_source_save(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.a7s"
            source.write_bytes(b"private")
            with self.assertRaisesRegex(ValueError, "aliases a source save"):
                target_check._write_report_atomic({}, source, [source])
            self.assertEqual(source.read_bytes(), b"private")

    def test_atomic_report_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.a7s"
            output = root / "evidence.json"
            source.write_bytes(b"private")
            report = {"schema": target_check.REPORT_SCHEMA, "schema_version": 1}
            target_check._write_report_atomic(report, output, [source])
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)
            self.assertEqual(source.read_bytes(), b"private")


if __name__ == "__main__":
    unittest.main()
