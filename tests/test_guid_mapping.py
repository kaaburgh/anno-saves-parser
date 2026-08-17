import json
import tempfile
import unittest
from pathlib import Path

from guid_mapping import (
    GUID_MAPPING_SCHEMA,
    GuidMappingError,
    enrich_structural_diff,
    load_guid_mapping,
    resolve_guid,
    validate_guid_mapping,
)


class GuidMappingTests(unittest.TestCase):
    def mapping_document(self):
        return {
            "schema": GUID_MAPPING_SCHEMA,
            "schema_version": 1,
            "provenance": {
                "source": "synthetic-test-catalog",
                "source_version": "fixture-1",
                "mapping_version": "2026-08-17-test",
                "source_hash": "sha256:synthetic",
            },
            "entries": {"1001": "Synthetic Residence", "2002": "Synthetic Factory"},
        }

    def test_exact_resolution_preserves_unknown_guid(self):
        mapping = validate_guid_mapping(self.mapping_document())
        self.assertEqual(resolve_guid(mapping, 1001), "Synthetic Residence")
        self.assertIsNone(resolve_guid(mapping, 1002))

    def test_enrichment_preserves_numeric_guid_and_attaches_provenance(self):
        mapping = validate_guid_mapping(self.mapping_document())
        raw = {
            "added": [{"guid": 1001, "id": 7}],
            "removed": [{"guid": 9999, "id": 8}],
            "moved": [],
            "component_changed": [],
            "direction_changed": [],
            "guid_changed": [{"from_guid": 1001, "to_guid": 2002, "id": 9}],
        }
        enriched = enrich_structural_diff(raw, mapping)

        self.assertNotIn("guid_mapping", raw)
        self.assertEqual(enriched["added"][0]["guid"], 1001)
        self.assertEqual(enriched["added"][0]["guid_name"], "Synthetic Residence")
        self.assertIsNone(enriched["removed"][0]["guid_name"])
        self.assertEqual(enriched["guid_changed"][0]["from_guid_name"], "Synthetic Residence")
        self.assertEqual(enriched["guid_changed"][0]["to_guid_name"], "Synthetic Factory")
        self.assertEqual(
            enriched["guid_mapping"]["provenance"]["source_version"], "fixture-1"
        )
        self.assertRegex(
            enriched["guid_mapping"]["provenance"]["mapping_content_hash"],
            r"^sha256:[0-9a-f]{64}$",
        )

    def test_mapping_content_hash_binds_resolved_names(self):
        first = self.mapping_document()
        second = self.mapping_document()
        second["entries"]["1001"] = "Different Synthetic Residence"

        first_mapping = validate_guid_mapping(first)
        second_mapping = validate_guid_mapping(second)

        self.assertEqual(
            first_mapping["provenance"]["mapping_version"],
            second_mapping["provenance"]["mapping_version"],
        )
        self.assertNotEqual(
            first_mapping["provenance"]["mapping_content_hash"],
            second_mapping["provenance"]["mapping_content_hash"],
        )

    def test_mapping_content_hash_is_stable_across_entry_order(self):
        first = self.mapping_document()
        second = self.mapping_document()
        second["entries"] = {
            "2002": "Synthetic Factory",
            "1001": "Synthetic Residence",
        }
        self.assertEqual(
            validate_guid_mapping(first)["provenance"]["mapping_content_hash"],
            validate_guid_mapping(second)["provenance"]["mapping_content_hash"],
        )

    def test_rejects_incompatible_schema_and_missing_provenance(self):
        bad_schema = self.mapping_document()
        bad_schema["schema_version"] = 2
        with self.assertRaises(GuidMappingError):
            validate_guid_mapping(bad_schema)

        missing = self.mapping_document()
        del missing["provenance"]["source_version"]
        with self.assertRaises(GuidMappingError):
            validate_guid_mapping(missing)

    def test_rejects_invalid_guid_keys_and_names(self):
        invalid_guid = self.mapping_document()
        invalid_guid["entries"] = {"0x3e9": "Hex is not the contract"}
        with self.assertRaises(GuidMappingError):
            validate_guid_mapping(invalid_guid)

        invalid_name = self.mapping_document()
        invalid_name["entries"] = {"1001": "   "}
        with self.assertRaises(GuidMappingError):
            validate_guid_mapping(invalid_name)

    def test_loader_rejects_duplicate_json_keys(self):
        payload = (
            '{"schema":"anno-saves-parser/guid-name-mapping","schema_version":1,'
            '"provenance":{"source":"x","source_version":"1","mapping_version":"1"},'
            '"entries":{"1001":"A","1001":"B"}}'
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "mapping.json"
            path.write_text(payload, encoding="utf8")
            with self.assertRaises(GuidMappingError):
                load_guid_mapping(path)

    def test_loader_round_trip_is_dependency_free_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "mapping.json"
            path.write_text(json.dumps(self.mapping_document()), encoding="utf8")
            mapping = load_guid_mapping(path)
            self.assertEqual(mapping["entries"][2002], "Synthetic Factory")
            self.assertRegex(
                mapping["provenance"]["mapping_content_hash"],
                r"^sha256:[0-9a-f]{64}$",
            )


if __name__ == "__main__":
    unittest.main()
