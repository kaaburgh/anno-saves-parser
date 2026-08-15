import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import anno_save_probe as probe


def state(source, objects, session_guid=123456, session_id=6):
    area_ids = sorted({obj["area_id"] for obj in objects})
    return {
        "schema": probe.CANONICAL_SCHEMA,
        "schema_version": probe.CANONICAL_SCHEMA_VERSION,
        "source": {"save_name": source},
        "sessions": [
            {
                "session_guid": session_guid,
                "session_id": session_id,
                "player_areas": [
                    {"area_id": area_id, "owner_id": 0} for area_id in area_ids
                ],
                "buildings": objects,
            }
        ],
    }


def building(object_id, guid, area_id=42, components=None, position=None):
    obj = {
        "id": object_id,
        "guid": guid,
        "area_id": area_id,
        "components": components or ["Building", "LogisticNode", "Residence7"],
    }
    if position is not None:
        obj["position"] = position
    return obj


class StructuralDiffGuidChangeTests(unittest.TestCase):
    def test_guid_only_change_is_one_mutation_without_add_remove_noise(self):
        prev = state("before.a7s", [building(101, 5001)])
        curr = state("after.a7s", [building(101, 5002)])

        diff = probe.diff_states(prev, curr)

        self.assertEqual(diff["added_count"], 0)
        self.assertEqual(diff["removed_count"], 0)
        self.assertEqual(diff["moved_count"], 0)
        self.assertEqual(diff["component_changed_count"], 0)
        self.assertEqual(diff["guid_changed_count"], 1)
        self.assertEqual(
            diff["guid_changed"],
            [
                {
                    "session_guid": 123456,
                    "session_id": 6,
                    "area_id": 42,
                    "id": 101,
                    "from_guid": 5001,
                    "to_guid": 5002,
                    "components": ["Building", "LogisticNode", "Residence7"],
                }
            ],
        )

    def test_multiple_guid_changes_are_sorted_by_stable_object_key(self):
        prev = state(
            "before.a7s",
            [
                building(30, 300, area_id=90),
                building(20, 200, area_id=80),
                building(10, 100, area_id=80),
            ],
        )
        curr = state(
            "after.a7s",
            [
                building(10, 101, area_id=80),
                building(30, 301, area_id=90),
                building(20, 201, area_id=80),
            ],
        )

        diff = probe.diff_states(prev, curr)

        self.assertEqual(diff["guid_changed_count"], 3)
        self.assertEqual(
            [(e["area_id"], e["id"]) for e in diff["guid_changed"]],
            [(80, 10), (80, 20), (90, 30)],
        )
        self.assertEqual(
            [(e["from_guid"], e["to_guid"]) for e in diff["guid_changed"]],
            [(100, 101), (200, 201), (300, 301)],
        )

    def test_missing_and_present_session_guids_sort_common_objects(self):
        prev = {
            "schema": probe.CANONICAL_SCHEMA,
            "schema_version": probe.CANONICAL_SCHEMA_VERSION,
            "source": {"save_name": "before.a7s"},
            "sessions": [
                {"session_guid": None, "session_id": 7, "player_areas": [], "buildings": [building(2, 200)]},
                {"session_guid": 123456, "session_id": 6, "player_areas": [], "buildings": [building(1, 100)]},
            ],
        }
        curr = {
            "schema": probe.CANONICAL_SCHEMA,
            "schema_version": probe.CANONICAL_SCHEMA_VERSION,
            "source": {"save_name": "after.a7s"},
            "sessions": [
                {"session_guid": None, "session_id": 7, "player_areas": [], "buildings": [building(2, 201)]},
                {"session_guid": 123456, "session_id": 6, "player_areas": [], "buildings": [building(1, 101)]},
            ],
        }

        diff = probe.diff_states(prev, curr)

        self.assertEqual(diff["guid_changed_count"], 2)
        self.assertEqual(
            [event["session_guid"] for event in diff["guid_changed"]],
            [123456, None],
        )

    def test_missing_and_present_session_guids_sort_added_and_removed_objects(self):
        prev = {
            "schema": probe.CANONICAL_SCHEMA,
            "schema_version": probe.CANONICAL_SCHEMA_VERSION,
            "source": {"save_name": "before.a7s"},
            "sessions": [
                {"session_guid": None, "session_id": 7, "player_areas": [], "buildings": [building(2, 200)]},
                {"session_guid": 123456, "session_id": 6, "player_areas": [], "buildings": [building(1, 100)]},
            ],
        }
        curr = {
            "schema": probe.CANONICAL_SCHEMA,
            "schema_version": probe.CANONICAL_SCHEMA_VERSION,
            "source": {"save_name": "after.a7s"},
            "sessions": [
                {"session_guid": None, "session_id": 7, "player_areas": [], "buildings": [building(4, 400)]},
                {"session_guid": 123456, "session_id": 6, "player_areas": [], "buildings": [building(3, 300)]},
            ],
        }

        diff = probe.diff_states(prev, curr)

        self.assertEqual(
            [event["session_guid"] for event in diff["added"]],
            [123456, None],
        )
        self.assertEqual(
            [event["session_guid"] for event in diff["removed"]],
            [123456, None],
        )

    def test_unchanged_guid_does_not_emit_event(self):
        prev = state("before.a7s", [building(1, 5001)])
        curr = state("after.a7s", [building(1, 5001)])

        diff = probe.diff_states(prev, curr)

        self.assertEqual(diff["guid_changed_count"], 0)
        self.assertEqual(diff["guid_changed"], [])

    def test_guid_change_remains_orthogonal_to_component_change(self):
        prev = state(
            "before.a7s",
            [building(1, 5001, components=["Building", "Residence7"])],
        )
        curr = state(
            "after.a7s",
            [building(1, 5002, components=["Building", "LogisticNode", "Residence7"])],
        )

        diff = probe.diff_states(prev, curr)

        self.assertEqual(diff["guid_changed_count"], 1)
        self.assertEqual(diff["component_changed_count"], 1)
        self.assertEqual(diff["added_count"], 0)
        self.assertEqual(diff["removed_count"], 0)

    def test_cli_pair_summary_reports_guid_change_count(self):
        saves = [Path("before.a7s"), Path("after.a7s")]
        states = [
            state("before.a7s", [building(1, 5001)]),
            state("after.a7s", [building(1, 5002)]),
        ]
        output = io.StringIO()

        with tempfile.TemporaryDirectory() as td:
            with (
                contextlib.redirect_stdout(output),
                patch.object(probe, "discover_saves", return_value=saves),
                patch.object(probe, "canonicalize_save", side_effect=states),
            ):
                probe.main([str(Path(td)), "-o", str(Path(td) / "out")])

        self.assertIn(
            "before.a7s -> after.a7s: +0 -0 moved=0 changed=0 guid_changed=1",
            output.getvalue(),
        )

    def test_legacy_pre_v1_state_is_rejected(self):
        legacy = {"source": "old.a7s", "sessions": []}
        current = state("new.a7s", [])

        with self.assertRaisesRegex(ValueError, "canonical state schema"):
            probe.diff_states(legacy, current)


if __name__ == "__main__":
    unittest.main(verbosity=2)
