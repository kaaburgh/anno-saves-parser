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


def building(object_id, guid, area_id=42, components=None, position=None, direction=None):
    obj = {
        "id": object_id,
        "guid": guid,
        "area_id": area_id,
        "components": components or ["Building", "LogisticNode", "Residence7"],
    }
    if position is not None:
        obj["position"] = position
    if direction is not None:
        obj["direction"] = direction
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

    def test_null_guid_sessions_with_reused_object_ids_do_not_overwrite_each_other(self):
        prev = {
            "schema": probe.CANONICAL_SCHEMA,
            "schema_version": probe.CANONICAL_SCHEMA_VERSION,
            "source": {"save_name": "before.a7s"},
            "sessions": [
                {"session_guid": None, "session_id": 1, "player_areas": [], "buildings": [building(5, 100)]},
                {"session_guid": None, "session_id": 2, "player_areas": [], "buildings": [building(5, 200)]},
            ],
        }
        curr = {
            "schema": probe.CANONICAL_SCHEMA,
            "schema_version": probe.CANONICAL_SCHEMA_VERSION,
            "source": {"save_name": "after.a7s"},
            "sessions": [
                {"session_guid": None, "session_id": 1, "player_areas": [], "buildings": [building(5, 101)]},
                {"session_guid": None, "session_id": 2, "player_areas": [], "buildings": [building(5, 200)]},
            ],
        }

        diff = probe.diff_states(prev, curr)

        self.assertEqual(diff["added_count"], 0)
        self.assertEqual(diff["removed_count"], 0)
        self.assertEqual(diff["guid_changed_count"], 1)
        self.assertEqual(diff["guid_changed"][0]["session_guid"], None)
        self.assertEqual(diff["guid_changed"][0]["session_id"], 1)
        self.assertEqual(diff["guid_changed"][0]["from_guid"], 100)
        self.assertEqual(diff["guid_changed"][0]["to_guid"], 101)

    def test_ambiguous_duplicate_session_identity_is_rejected(self):
        ambiguous = {
            "schema": probe.CANONICAL_SCHEMA,
            "schema_version": probe.CANONICAL_SCHEMA_VERSION,
            "source": {"save_name": "ambiguous.a7s"},
            "sessions": [
                {"session_guid": None, "session_id": 1, "map": "same.a7t", "player_areas": [], "buildings": [building(1, 100)]},
                {"session_guid": None, "session_id": 1, "map": "same.a7t", "player_areas": [], "buildings": [building(2, 200)]},
            ],
        }

        with self.assertRaisesRegex(ValueError, "duplicate canonical session identity"):
            probe.diff_states(ambiguous, ambiguous)

    def test_session_without_any_diff_identity_is_rejected(self):
        anonymous = {
            "schema": probe.CANONICAL_SCHEMA,
            "schema_version": probe.CANONICAL_SCHEMA_VERSION,
            "source": {"save_name": "anonymous.a7s"},
            "sessions": [
                {"session_guid": None, "session_id": None, "player_areas": [], "buildings": [building(1, 100)]},
            ],
        }

        with self.assertRaisesRegex(ValueError, "cannot identify a session"):
            probe.diff_states(anonymous, anonymous)

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
            "before.a7s -> after.a7s: +0 -0 moved=0 changed=0 guid_changed=1 direction_changed=0",
            output.getvalue(),
        )

    def test_legacy_pre_v1_state_is_rejected(self):
        legacy = {"source": "old.a7s", "sessions": []}
        current = state("new.a7s", [])

        with self.assertRaisesRegex(ValueError, "canonical state schema"):
            probe.diff_states(legacy, current)


class StructuralDiffDirectionChangeTests(unittest.TestCase):
    def test_direction_only_change_is_observable_without_lifecycle_noise(self):
        prev = state("before.a7s", [building(101, 5001, direction=1.5)])
        curr = state("after.a7s", [building(101, 5001, direction=2.5)])

        diff = probe.diff_states(prev, curr)

        self.assertEqual(diff["added_count"], 0)
        self.assertEqual(diff["removed_count"], 0)
        self.assertEqual(diff["moved_count"], 0)
        self.assertEqual(diff["component_changed_count"], 0)
        self.assertEqual(diff["guid_changed_count"], 0)
        self.assertEqual(diff["direction_changed_count"], 1)
        self.assertEqual(
            diff["direction_changed"],
            [
                {
                    "session_guid": 123456,
                    "session_id": 6,
                    "area_id": 42,
                    "id": 101,
                    "guid": 5001,
                    "from_direction": 1.5,
                    "to_direction": 2.5,
                    "components": ["Building", "LogisticNode", "Residence7"],
                }
            ],
        )

    def test_direction_change_coexists_with_guid_and_move_events(self):
        prev = state(
            "before.a7s",
            [building(101, 5001, position=[1.0, 2.0, 3.0], direction=1.5)],
        )
        curr = state(
            "after.a7s",
            [building(101, 5002, position=[4.0, 2.0, 3.0], direction=2.5)],
        )

        diff = probe.diff_states(prev, curr)

        self.assertEqual(diff["guid_changed_count"], 1)
        self.assertEqual(diff["moved_count"], 1)
        self.assertEqual(diff["direction_changed_count"], 1)
        self.assertEqual(diff["direction_changed"][0]["id"], 101)
        self.assertEqual(diff["direction_changed"][0]["guid"], 5002)

    def test_present_absent_direction_transitions_preserve_observed_absence(self):
        cases = (
            (building(1, 5001, direction=1.5), building(1, 5001), 1.5, None),
            (building(1, 5001), building(1, 5001, direction=1.5), None, 1.5),
        )
        for before_obj, after_obj, expected_from, expected_to in cases:
            with self.subTest(expected_from=expected_from, expected_to=expected_to):
                diff = probe.diff_states(
                    state("before.a7s", [before_obj]),
                    state("after.a7s", [after_obj]),
                )
                self.assertEqual(diff["direction_changed_count"], 1)
                event = diff["direction_changed"][0]
                self.assertEqual(event["from_direction"], expected_from)
                self.assertEqual(event["to_direction"], expected_to)

    def test_unchanged_or_absent_direction_emits_nothing(self):
        for before_obj, after_obj in (
            (building(1, 5001, direction=1.5), building(1, 5001, direction=1.5)),
            (building(1, 5001), building(1, 5001)),
        ):
            with self.subTest(before=before_obj, after=after_obj):
                diff = probe.diff_states(
                    state("before.a7s", [before_obj]),
                    state("after.a7s", [after_obj]),
                )
                self.assertEqual(diff["direction_changed_count"], 0)
                self.assertEqual(diff["direction_changed"], [])

    def test_direction_events_are_sorted_by_stable_object_key(self):
        prev = state(
            "before.a7s",
            [
                building(30, 300, area_id=90, direction=1.0),
                building(20, 200, area_id=80, direction=1.0),
                building(10, 100, area_id=80, direction=1.0),
            ],
        )
        curr = state(
            "after.a7s",
            [
                building(10, 100, area_id=80, direction=2.0),
                building(30, 300, area_id=90, direction=2.0),
                building(20, 200, area_id=80, direction=2.0),
            ],
        )

        diff = probe.diff_states(prev, curr)

        self.assertEqual(
            [(event["area_id"], event["id"]) for event in diff["direction_changed"]],
            [(80, 10), (80, 20), (90, 30)],
        )

    def test_direction_event_preserves_fallback_session_identity(self):
        prev = state(
            "before.a7s",
            [building(1, 5001, direction=1.0)],
            session_guid=None,
            session_id=7,
        )
        curr = state(
            "after.a7s",
            [building(1, 5001, direction=2.0)],
            session_guid=None,
            session_id=7,
        )

        event = probe.diff_states(prev, curr)["direction_changed"][0]

        self.assertIsNone(event["session_guid"])
        self.assertEqual(event["session_id"], 7)

    def test_direction_events_preserve_map_for_guidless_session_fallbacks(self):
        prev = {
            "schema": probe.CANONICAL_SCHEMA,
            "schema_version": probe.CANONICAL_SCHEMA_VERSION,
            "source": {"save_name": "before.a7s"},
            "sessions": [
                {
                    "session_guid": None,
                    "session_id": 7,
                    "map": "maps/a.a7t",
                    "player_areas": [],
                    "buildings": [building(1, 5001, direction=1.0)],
                },
                {
                    "session_guid": None,
                    "session_id": 7,
                    "map": "maps/b.a7t",
                    "player_areas": [],
                    "buildings": [building(1, 5001, direction=3.0)],
                },
            ],
        }
        curr = {
            "schema": probe.CANONICAL_SCHEMA,
            "schema_version": probe.CANONICAL_SCHEMA_VERSION,
            "source": {"save_name": "after.a7s"},
            "sessions": [
                {
                    "session_guid": None,
                    "session_id": 7,
                    "map": "maps/b.a7t",
                    "player_areas": [],
                    "buildings": [building(1, 5001, direction=4.0)],
                },
                {
                    "session_guid": None,
                    "session_id": 7,
                    "map": "maps/a.a7t",
                    "player_areas": [],
                    "buildings": [building(1, 5001, direction=2.0)],
                },
            ],
        }

        events = probe.diff_states(prev, curr)["direction_changed"]

        self.assertEqual([event["map"] for event in events], ["maps/a.a7t", "maps/b.a7t"])
        self.assertEqual([event["session_id"] for event in events], [7, 7])
        self.assertEqual([event["id"] for event in events], [1, 1])

    def test_cli_pair_summary_reports_direction_change_count(self):
        saves = [Path("before.a7s"), Path("after.a7s")]
        states = [
            state("before.a7s", [building(1, 5001, direction=1.0)]),
            state("after.a7s", [building(1, 5001, direction=2.0)]),
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
            "before.a7s -> after.a7s: +0 -0 moved=0 changed=0 guid_changed=0 direction_changed=1",
            output.getvalue(),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
