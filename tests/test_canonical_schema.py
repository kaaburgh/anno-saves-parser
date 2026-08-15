import copy
import unittest

import anno_save_probe as probe


class CanonicalSchemaV1Tests(unittest.TestCase):
    def _raw_sessions(self):
        return [
            {
                "index": 8,
                "id": 9,
                "binary_size": 999,
                "player_area_ids": [20],
                "areas": {
                    "20": {
                        "owner_id": 0,
                        "building_objects": 1,
                        "kind_counts": {"building": 1},
                        "guid_counts": {"900": 1},
                    }
                },
                "player_buildings": [
                    {
                        "area_id": 20,
                        "id": 5,
                        "guid": 900,
                        "components": ["Warehouse", "Building", "Warehouse"],
                    }
                ],
                "total_game_objects": 1234,
            },
            {
                "index": 2,
                "guid": 100,
                "id": 2,
                "map": "synthetic/session.a7t",
                "binary_size": 123,
                "player_area_ids": [7, 3],
                "areas": {
                    "7": {
                        "owner_id": 0,
                        "city_name_iterator": 2,
                        "building_objects": 1,
                        "kind_counts": {"residence": 1},
                        "guid_counts": {"502": 1},
                    },
                    "3": {
                        "owner_id": 0,
                        "city_name_guid": 700,
                        "building_objects": 1,
                        "kind_counts": {"warehouse": 1},
                        "guid_counts": {"501": 1},
                    },
                },
                "player_buildings": [
                    {
                        "area_id": 7,
                        "id": 20,
                        "guid": 502,
                        "components": ["Residence7", "Building"],
                        "rotation": 2,
                    },
                    {
                        "area_id": 3,
                        "id": 10,
                        "guid": 501,
                        "components": ["Warehouse", "Building", "Warehouse"],
                        "position": [1.5, 2.5, 3.5],
                        "direction": 1.25,
                    },
                ],
                "total_game_objects": 4321,
            },
        ]

    def test_exact_v1_shape_excludes_parser_only_and_derived_fields(self):
        state = probe.build_canonical_state("Synthetic Save.a7s", self._raw_sessions())

        self.assertEqual(
            state,
            {
                "schema": "anno-saves-parser/canonical-state",
                "schema_version": 1,
                "source": {"save_name": "Synthetic Save.a7s"},
                "sessions": [
                    {
                        "session_guid": 100,
                        "session_id": 2,
                        "map": "synthetic/session.a7t",
                        "player_areas": [
                            {"area_id": 3, "owner_id": 0, "city_name_guid": 700},
                            {"area_id": 7, "owner_id": 0, "city_name_iterator": 2},
                        ],
                        "buildings": [
                            {
                                "area_id": 3,
                                "id": 10,
                                "guid": 501,
                                "components": ["Building", "Warehouse"],
                                "position": [1.5, 2.5, 3.5],
                                "direction": 1.25,
                            },
                            {
                                "area_id": 7,
                                "id": 20,
                                "guid": 502,
                                "components": ["Building", "Residence7"],
                                "rotation": 2,
                            },
                        ],
                    },
                    {
                        "session_guid": None,
                        "session_id": 9,
                        "player_areas": [{"area_id": 20, "owner_id": 0}],
                        "buildings": [
                            {
                                "area_id": 20,
                                "id": 5,
                                "guid": 900,
                                "components": ["Building", "Warehouse"],
                            }
                        ],
                    },
                ],
            },
        )

        serialized = repr(state)
        for parser_only in (
            "binary_size",
            "total_game_objects",
            "building_objects",
            "kind_counts",
            "guid_counts",
            "index",
        ):
            self.assertNotIn(parser_only, serialized)

    def test_normalization_is_deterministic_from_shuffled_internal_order(self):
        first = self._raw_sessions()
        second = copy.deepcopy(first)
        second.reverse()
        for session in second:
            session["player_area_ids"].reverse()
            session["player_buildings"].reverse()
            for obj in session["player_buildings"]:
                obj["components"].reverse()

        self.assertEqual(
            probe.build_canonical_state("same.a7s", first),
            probe.build_canonical_state("same.a7s", second),
        )

    def test_missing_optional_fields_remain_absent_while_session_identity_is_explicit(self):
        state = probe.build_canonical_state(
            "minimal.a7s",
            [
                {
                    "id": 5,
                    "player_area_ids": [1],
                    "areas": {"1": {"owner_id": 0}},
                    "player_buildings": [
                        {
                            "area_id": 1,
                            "id": 2,
                            "guid": 3,
                            "components": ["Building"],
                        }
                    ],
                }
            ],
        )

        session = state["sessions"][0]
        building = session["buildings"][0]
        self.assertIsNone(session["session_guid"])
        self.assertEqual(session["session_id"], 5)
        self.assertNotIn("map", session)
        self.assertNotIn("position", building)
        self.assertNotIn("direction", building)
        self.assertNotIn("rotation", building)

    def test_summary_keeps_contract_metadata_and_omits_building_arrays(self):
        state = probe.build_canonical_state("Synthetic Save.a7s", self._raw_sessions())

        summary = probe.strip_objects(state)

        self.assertEqual(summary["schema"], probe.CANONICAL_SCHEMA)
        self.assertEqual(summary["schema_version"], 1)
        self.assertEqual(summary["source"], {"save_name": "Synthetic Save.a7s"})
        self.assertEqual(summary["sessions"][0]["building_count"], 2)
        self.assertEqual(summary["sessions"][1]["building_count"], 1)
        self.assertEqual(summary["sessions"][0]["player_areas"][0]["area_id"], 3)
        self.assertNotIn("buildings", summary["sessions"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
