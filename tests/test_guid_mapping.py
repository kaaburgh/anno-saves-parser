import copy
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

    def structured_mapping_document(self):
        document = self.mapping_document()
        document["provenance"].update(
            {
                "extractor": {
                    "identity": "anno-mods/asset-extractor@3.0",
                    "artifact_hash": "sha256:" + "a" * 64,
                },
                "converter": {
                    "identity": "anno-saves-parser/guid_mapping_export.py@fixture",
                    "artifact_hash": "sha256:" + "b" * 64,
                },
                "input_hashes": {
                    "assets": "sha256:" + "c" * 64,
                    "localization-en": "sha256:" + "d" * 64,
                },
            }
        )
        return document

    def test_exact_resolution_preserves_unknown_guid(self):
        mapping = validate_guid_mapping(self.mapping_document())
        self.assertEqual(resolve_guid(mapping, 1001), "Synthetic Residence")
        self.assertIsNone(resolve_guid(mapping, 1002))

    def test_existing_schema_v1_mapping_without_structured_provenance_remains_valid(self):
        mapping = validate_guid_mapping(self.mapping_document())
        self.assertNotIn("extractor", mapping["provenance"])
        self.assertNotIn("converter", mapping["provenance"])
        self.assertNotIn("input_hashes", mapping["provenance"])

    def test_structured_provenance_survives_validation_and_enrichment(self):
        mapping = validate_guid_mapping(self.structured_mapping_document())
        self.assertEqual(
            mapping["provenance"]["extractor"]["identity"],
            "anno-mods/asset-extractor@3.0",
        )
        self.assertEqual(
            mapping["provenance"]["converter"]["identity"],
            "anno-saves-parser/guid_mapping_export.py@fixture",
        )
        self.assertEqual(
            list(mapping["provenance"]["input_hashes"]),
            ["assets", "localization-en"],
        )
        enriched = enrich_structural_diff({"added": [{"guid": 1001}]}, mapping)
        self.assertEqual(
            enriched["guid_mapping"]["provenance"]["extractor"],
            mapping["provenance"]["extractor"],
        )
        self.assertEqual(
            enriched["guid_mapping"]["provenance"]["input_hashes"],
            mapping["provenance"]["input_hashes"],
        )

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

    def test_mapping_content_hash_binds_producer_and_input_identities(self):
        original = self.structured_mapping_document()
        original_hash = validate_guid_mapping(original)["provenance"]["mapping_content_hash"]

        variants = []
        changed_extractor = copy.deepcopy(original)
        changed_extractor["provenance"]["extractor"]["identity"] = "asset-extractor@different"
        variants.append(changed_extractor)
        changed_converter = copy.deepcopy(original)
        changed_converter["provenance"]["converter"]["identity"] = "converter@different"
        variants.append(changed_converter)
        changed_input = copy.deepcopy(original)
        changed_input["provenance"]["input_hashes"]["assets"] = "sha256:" + "e" * 64
        variants.append(changed_input)

        for variant in variants:
            with self.subTest(provenance=variant["provenance"]):
                self.assertNotEqual(
                    original_hash,
                    validate_guid_mapping(variant)["provenance"]["mapping_content_hash"],
                )

    def test_mapping_content_hash_is_stable_across_entry_and_input_order(self):
        first = self.structured_mapping_document()
        second = self.structured_mapping_document()
        second["entries"] = {
            "2002": "Synthetic Factory",
            "1001": "Synthetic Residence",
        }
        second["provenance"]["input_hashes"] = {
            "localization-en": "sha256:" + "d" * 64,
            "assets": "sha256:" + "c" * 64,
        }
        self.assertEqual(
            validate_guid_mapping(first)["provenance"]["mapping_content_hash"],
            validate_guid_mapping(second)["provenance"]["mapping_content_hash"],
        )

    def test_rejects_unknown_provenance_fields(self):
        unknown = self.mapping_document()
        unknown["provenance"]["extractor_release"] = "3.0"
        with self.assertRaisesRegex(GuidMappingError, "unsupported provenance field"):
            validate_guid_mapping(unknown)

        nested_unknown = self.structured_mapping_document()
        nested_unknown["provenance"]["extractor"]["commit"] = "deadbeef"
        with self.assertRaisesRegex(GuidMappingError, "unsupported provenance.extractor field"):
            validate_guid_mapping(nested_unknown)

    def test_rejects_invalid_structured_provenance_hashes(self):
        invalid = self.structured_mapping_document()
        invalid["provenance"]["input_hashes"]["assets"] = "sha256:not-a-digest"
        with self.assertRaisesRegex(GuidMappingError, "64 hex"):
            validate_guid_mapping(invalid)

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
            path.write_text(json.dumps(self.structured_mapping_document()), encoding="utf8")
            mapping = load_guid_mapping(path)
            self.assertEqual(mapping["entries"][2002], "Synthetic Factory")
            self.assertEqual(
                mapping["provenance"]["extractor"]["artifact_hash"],
                "sha256:" + "a" * 64,
            )
            self.assertRegex(
                mapping["provenance"]["mapping_content_hash"],
                r"^sha256:[0-9a-f]{64}$",
            )


if __name__ == "__main__":
    unittest.main()
