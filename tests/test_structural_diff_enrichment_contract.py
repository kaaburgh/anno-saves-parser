import unittest

import anno_save_probe as probe
from guid_mapping import enrich_structural_diff, validate_guid_mapping


OBJECT_SECTIONS = (
    "added",
    "removed",
    "moved",
    "component_changed",
    "guid_changed",
    "direction_changed",
)


def building(
    object_id,
    guid,
    *,
    position=None,
    direction=None,
    components=None,
):
    obj = {
        "area_id": 42,
        "id": object_id,
        "guid": guid,
        "components": components or ["Building"],
    }
    if position is not None:
        obj["position"] = position
    if direction is not None:
        obj["direction"] = direction
    return obj


def state(source, buildings):
    return {
        "schema": probe.CANONICAL_SCHEMA,
        "schema_version": probe.CANONICAL_SCHEMA_VERSION,
        "source": {"save_name": source},
        "sessions": [
            {
                "session_guid": None,
                "session_id": 7,
                "map": "maps/synthetic.a7t",
                "player_areas": [{"area_id": 42, "owner_id": 0}],
                "buildings": buildings,
            }
        ],
    }


def mapping():
    return validate_guid_mapping(
        {
            "schema": "anno-saves-parser/guid-name-mapping",
            "schema_version": 1,
            "provenance": {
                "source": "synthetic",
                "source_version": "test",
                "mapping_version": "test",
            },
            "entries": {
                "100": "Moved",
                "200": "Removed",
                "300": "Components",
                "400": "Direction",
                "500": "Old GUID",
                "501": "New GUID",
                "600": "Added",
            },
        }
    )


class StructuralDiffEnrichmentContractTests(unittest.TestCase):
    def setUp(self):
        self.prev = state(
            "before.a7s",
            [
                building(1, 100, position=[0.0, 0.0, 0.0]),
                building(2, 200),
                building(3, 300, components=["Building"]),
                building(4, 400, direction=1.0),
                building(5, 500),
            ],
        )
        self.curr = state(
            "after.a7s",
            [
                building(1, 100, position=[1.0, 0.0, 0.0]),
                building(3, 300, components=["Building", "Warehouse"]),
                building(4, 400, direction=2.0),
                building(5, 501),
                building(6, 600),
            ],
        )

    def test_all_object_events_share_canonical_session_attribution(self):
        diff = probe.diff_states(self.prev, self.curr)
        expected = {
            "session_guid": None,
            "session_id": 7,
            "map": "maps/synthetic.a7t",
        }

        for section in OBJECT_SECTIONS:
            with self.subTest(section=section):
                self.assertEqual(len(diff[section]), 1)
                event = diff[section][0]
                self.assertEqual(
                    {key: event[key] for key in expected},
                    expected,
                )

    def test_enrichment_follows_guid_fields_across_producer_output(self):
        diff = probe.diff_states(self.prev, self.curr)
        enriched = enrich_structural_diff(diff, mapping())

        for section in OBJECT_SECTIONS:
            for event in enriched[section]:
                with self.subTest(section=section, event=event):
                    if "guid" in event:
                        self.assertIn("guid_name", event)
                    if "from_guid" in event:
                        self.assertEqual(event["from_guid_name"], "Old GUID")
                    if "to_guid" in event:
                        self.assertEqual(event["to_guid_name"], "New GUID")

        self.assertEqual(enriched["added"][0]["guid_name"], "Added")
        self.assertEqual(enriched["removed"][0]["guid_name"], "Removed")
        self.assertEqual(enriched["moved"][0]["guid_name"], "Moved")
        self.assertEqual(enriched["component_changed"][0]["guid_name"], "Components")
        self.assertEqual(enriched["direction_changed"][0]["guid_name"], "Direction")

    def test_enrichment_is_not_coupled_to_known_section_names(self):
        diff = probe.diff_states(self.prev, self.curr)
        diff["future_guid_event"] = [{"guid": 600}]

        enriched = enrich_structural_diff(diff, mapping())

        self.assertEqual(
            enriched["future_guid_event"],
            [{"guid": 600, "guid_name": "Added"}],
        )


if __name__ == "__main__":
    unittest.main()
