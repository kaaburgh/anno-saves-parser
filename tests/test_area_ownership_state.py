import unittest

import anno_save_probe as probe


def _state(save_name, *, observed_areas, player_areas):
    return {
        "schema": probe.CANONICAL_SCHEMA,
        "schema_version": probe.CANONICAL_SCHEMA_VERSION,
        "source": {"save_name": save_name},
        "sessions": [
            {
                "session_guid": 123456,
                "session_id": 7,
                "map": "synthetic/session.a7t",
                "observed_areas": observed_areas,
                "player_areas": player_areas,
                "buildings": [],
            }
        ],
    }


class AreaOwnershipStateTests(unittest.TestCase):
    def test_canonical_observed_areas_are_additive_and_sorted(self):
        state = probe.build_canonical_state(
            "Synthetic.a7s",
            [
                {
                    "guid": 123456,
                    "id": 7,
                    "map": "synthetic/session.a7t",
                    "observed_areas": [
                        {"area_id": 99, "owner_id": 3},
                        {"area_id": 42, "owner_id": 0},
                        {"area_id": 77},
                    ],
                    "player_area_ids": [42],
                    "areas": {"42": {"owner_id": 0}},
                    "player_buildings": [],
                }
            ],
        )
        session = state["sessions"][0]
        self.assertEqual(
            session["observed_areas"],
            [
                {"area_id": 42, "owner_id": 0},
                {"area_id": 77},
                {"area_id": 99, "owner_id": 3},
            ],
        )
        self.assertEqual(session["player_areas"], [{"area_id": 42, "owner_id": 0}])

    def test_duplicate_observed_area_identity_fails_closed(self):
        with self.assertRaisesRegex(
            ValueError,
            r"duplicate observed area identity",
        ):
            probe.build_canonical_state(
                "Synthetic.a7s",
                [
                    {
                        "guid": 123456,
                        "id": 7,
                        "observed_areas": [
                            {"area_id": 42, "owner_id": 3},
                            {"area_id": 42, "owner_id": 0},
                        ],
                        "player_area_ids": [],
                        "areas": {},
                        "player_buildings": [],
                    }
                ],
            )

    def test_non_player_to_player_emits_owner_transition_and_projection_add(self):
        prev = _state(
            "Prev.a7s",
            observed_areas=[{"area_id": 42, "owner_id": 3}],
            player_areas=[],
        )
        curr = _state(
            "Curr.a7s",
            observed_areas=[{"area_id": 42, "owner_id": 0}],
            player_areas=[{"area_id": 42, "owner_id": 0}],
        )
        diff = probe.diff_states(prev, curr)
        self.assertEqual(diff["area_added_count"], 1)
        self.assertEqual(
            diff["area_owner_changed"],
            [
                {
                    "session_guid": 123456,
                    "session_id": 7,
                    "map": "synthetic/session.a7t",
                    "area_id": 42,
                    "from_owner_id": 3,
                    "to_owner_id": 0,
                }
            ],
        )

    def test_newly_observed_player_area_has_no_owner_transition(self):
        prev = _state("Prev.a7s", observed_areas=[], player_areas=[])
        curr = _state(
            "Curr.a7s",
            observed_areas=[{"area_id": 42, "owner_id": 0}],
            player_areas=[{"area_id": 42, "owner_id": 0}],
        )
        diff = probe.diff_states(prev, curr)
        self.assertEqual(diff["area_added_count"], 1)
        self.assertEqual(diff["area_owner_changed_count"], 0)
        self.assertEqual(diff["area_owner_changed"], [])

    def test_unchanged_owner_has_no_owner_transition(self):
        prev = _state(
            "Prev.a7s",
            observed_areas=[{"area_id": 42, "owner_id": 3}],
            player_areas=[],
        )
        curr = _state(
            "Curr.a7s",
            observed_areas=[{"area_id": 42, "owner_id": 3}],
            player_areas=[],
        )
        diff = probe.diff_states(prev, curr)
        self.assertEqual(diff["area_owner_changed_count"], 0)

    def test_missing_owner_does_not_invent_transition(self):
        prev = _state(
            "Prev.a7s",
            observed_areas=[{"area_id": 42}],
            player_areas=[],
        )
        curr = _state(
            "Curr.a7s",
            observed_areas=[{"area_id": 42, "owner_id": 0}],
            player_areas=[{"area_id": 42, "owner_id": 0}],
        )
        diff = probe.diff_states(prev, curr)
        self.assertEqual(diff["area_owner_changed_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
