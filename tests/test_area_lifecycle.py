import unittest

import anno_save_probe as probe


def building(object_id, guid, area_id):
    return {
        "id": object_id,
        "guid": guid,
        "area_id": area_id,
        "components": ["Building"],
    }


def state(source, areas, buildings=None, *, session_guid=123456, session_id=6, map_name=None):
    session = {
        "session_guid": session_guid,
        "session_id": session_id,
        "player_areas": [
            {"area_id": area_id, "owner_id": 0} for area_id in areas
        ],
        "buildings": buildings or [],
    }
    if map_name is not None:
        session["map"] = map_name
    return {
        "schema": probe.CANONICAL_SCHEMA,
        "schema_version": probe.CANONICAL_SCHEMA_VERSION,
        "source": {"save_name": source},
        "sessions": [session],
    }


class StructuralDiffAreaLifecycleTests(unittest.TestCase):
    def test_area_appearance_emits_explicit_raw_event(self):
        prev = state("before.a7s", [10])
        curr = state("after.a7s", [10, 20])

        diff = probe.diff_states(prev, curr)

        self.assertEqual(diff["area_added_count"], 1)
        self.assertEqual(diff["area_removed_count"], 0)
        self.assertEqual(
            diff["area_added"],
            [{"session_guid": 123456, "session_id": 6, "area_id": 20}],
        )
        self.assertEqual(diff["area_removed"], [])

    def test_area_disappearance_emits_explicit_raw_event(self):
        prev = state("before.a7s", [10, 20])
        curr = state("after.a7s", [10])

        diff = probe.diff_states(prev, curr)

        self.assertEqual(diff["area_added_count"], 0)
        self.assertEqual(diff["area_removed_count"], 1)
        self.assertEqual(
            diff["area_removed"],
            [{"session_guid": 123456, "session_id": 6, "area_id": 20}],
        )

    def test_unchanged_area_presence_emits_no_lifecycle_event(self):
        diff = probe.diff_states(
            state("before.a7s", [10, 20]),
            state("after.a7s", [10, 20]),
        )

        self.assertEqual(diff["area_added_count"], 0)
        self.assertEqual(diff["area_removed_count"], 0)
        self.assertEqual(diff["area_added"], [])
        self.assertEqual(diff["area_removed"], [])

    def test_area_event_does_not_absorb_nested_object_additions(self):
        prev = state("before.a7s", [10])
        curr = state(
            "after.a7s",
            [10, 20],
            [building(101, 5001, 20), building(102, 5002, 20)],
        )

        diff = probe.diff_states(prev, curr)

        self.assertEqual(diff["area_added_count"], 1)
        self.assertEqual(diff["added_count"], 2)
        self.assertEqual([event["id"] for event in diff["added"]], [101, 102])

    def test_area_event_does_not_absorb_nested_object_removals(self):
        prev = state(
            "before.a7s",
            [10, 20],
            [building(101, 5001, 20), building(102, 5002, 20)],
        )
        curr = state("after.a7s", [10])

        diff = probe.diff_states(prev, curr)

        self.assertEqual(diff["area_removed_count"], 1)
        self.assertEqual(diff["removed_count"], 2)
        self.assertEqual([event["id"] for event in diff["removed"]], [101, 102])

    def test_empty_area_lifecycle_is_observable_without_objects(self):
        diff = probe.diff_states(
            state("before.a7s", []),
            state("after.a7s", [20]),
        )

        self.assertEqual(diff["area_added_count"], 1)
        self.assertEqual(diff["added_count"], 0)

    def test_guidless_fallback_preserves_map_attribution(self):
        diff = probe.diff_states(
            state(
                "before.a7s",
                [],
                session_guid=None,
                session_id=7,
                map_name="maps/synthetic.a7t",
            ),
            state(
                "after.a7s",
                [20],
                session_guid=None,
                session_id=7,
                map_name="maps/synthetic.a7t",
            ),
        )

        self.assertEqual(
            diff["area_added"],
            [
                {
                    "session_guid": None,
                    "session_id": 7,
                    "map": "maps/synthetic.a7t",
                    "area_id": 20,
                }
            ],
        )

    def test_multiple_area_events_are_sorted_by_session_then_area(self):
        prev = {
            "schema": probe.CANONICAL_SCHEMA,
            "schema_version": probe.CANONICAL_SCHEMA_VERSION,
            "source": {"save_name": "before.a7s"},
            "sessions": [
                {
                    "session_guid": None,
                    "session_id": 7,
                    "map": "maps/b.a7t",
                    "player_areas": [],
                    "buildings": [],
                },
                {
                    "session_guid": 100,
                    "session_id": 1,
                    "player_areas": [],
                    "buildings": [],
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
                    "player_areas": [
                        {"area_id": 30, "owner_id": 0},
                        {"area_id": 20, "owner_id": 0},
                    ],
                    "buildings": [],
                },
                {
                    "session_guid": 100,
                    "session_id": 1,
                    "player_areas": [{"area_id": 40, "owner_id": 0}],
                    "buildings": [],
                },
            ],
        }

        events = probe.diff_states(prev, curr)["area_added"]

        self.assertEqual(
            [(event["session_guid"], event["area_id"]) for event in events],
            [(100, 40), (None, 20), (None, 30)],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
