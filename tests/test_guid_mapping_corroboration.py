from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from guid_mapping import GUID_MAPPING_SCHEMA, GUID_MAPPING_SCHEMA_VERSION, GuidMappingError
from guid_mapping_corroboration import (
    CORROBORATION_SCHEMA,
    OBSERVATIONS_SCHEMA,
    build_corroboration_record,
    load_observations,
    write_corroboration_record,
)


class GuidMappingCorroborationTests(unittest.TestCase):
    def _write_mapping(self, root: Path) -> Path:
        path = root / "guid-mapping.json"
        document = {
            "schema": GUID_MAPPING_SCHEMA,
            "schema_version": GUID_MAPPING_SCHEMA_VERSION,
            "provenance": {
                "source": "operator-owned-anno1800-installation",
                "source_version": "build-1",
                "mapping_version": "mapping-1",
                "source_hash": "sha256:" + "1" * 64,
                "extractor": {"identity": "asset-extractor@3.0"},
                "converter": {"identity": "guid_mapping_export.py@test"},
                "input_hashes": {"assets": "sha256:" + "2" * 64},
            },
            "entries": {
                "100": "Alpha",
                "200": "Beta",
                "300": "Unselected",
            },
        }
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf8",
        )
        return path

    def _write_observations(
        self,
        root: Path,
        *,
        checks: list[dict[str, object]] | None = None,
        reference: dict[str, str] | None = None,
    ) -> Path:
        path = root / "corroboration-observations.json"
        document = {
            "schema": OBSERVATIONS_SCHEMA,
            "schema_version": 1,
            "reference": reference
            or {
                "identity": "independent-reference",
                "version": "snapshot-1",
                "artifact_hash": "sha256:" + "3" * 64,
            },
            "checks": checks
            or [
                {"guid": 200, "name": "Beta", "locator": "reference:item-200"},
                {"guid": 100, "name": "Alpha"},
            ],
        }
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf8",
        )
        return path

    def test_build_record_binds_exact_inputs_and_only_checked_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mapping = self._write_mapping(root)
            observations = self._write_observations(root)

            record = build_corroboration_record(mapping, observations)

            self.assertEqual(record["schema"], CORROBORATION_SCHEMA)
            self.assertEqual(record["result"], {"status": "matched", "check_count": 2})
            self.assertEqual([item["guid"] for item in record["checks"]], [100, 200])
            self.assertNotIn("Unselected", json.dumps(record))
            self.assertEqual(
                record["mapping"]["file_sha256"],
                "sha256:" + hashlib.sha256(mapping.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                record["observations"]["file_sha256"],
                "sha256:" + hashlib.sha256(observations.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                record["independence"]["status"],
                "operator-asserted-independent-reference",
            )

    def test_mismatch_and_missing_guid_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mapping = self._write_mapping(root)

            mismatch = self._write_observations(
                root,
                checks=[{"guid": 100, "name": "Wrong"}],
            )
            with self.assertRaisesRegex(GuidMappingError, "corroboration mismatch"):
                build_corroboration_record(mapping, mismatch)

            missing = self._write_observations(
                root,
                checks=[{"guid": 999, "name": "Missing"}],
            )
            with self.assertRaisesRegex(GuidMappingError, "absent from the mapping"):
                build_corroboration_record(mapping, missing)

    def test_observations_reject_duplicate_guid_and_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            duplicate = self._write_observations(
                root,
                checks=[
                    {"guid": 100, "name": "Alpha"},
                    {"guid": 100, "name": "Alpha"},
                ],
            )
            with self.assertRaisesRegex(GuidMappingError, "duplicate corroboration GUID"):
                load_observations(duplicate)

            unknown = self._write_observations(root)
            document = json.loads(unknown.read_text(encoding="utf8"))
            document["reference"]["unexpected"] = "value"
            unknown.write_text(json.dumps(document), encoding="utf8")
            with self.assertRaisesRegex(GuidMappingError, "unsupported reference field"):
                load_observations(unknown)

    def test_observations_reject_malformed_reference_hash_and_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            malformed = self._write_observations(
                root,
                reference={
                    "identity": "independent-reference",
                    "version": "snapshot-1",
                    "artifact_hash": "not-a-sha256",
                },
            )
            with self.assertRaisesRegex(GuidMappingError, "reference.artifact_hash"):
                load_observations(malformed)

            duplicate_json = root / "duplicate.json"
            duplicate_json.write_text(
                '{"schema":"x","schema":"y","schema_version":1,"reference":{},"checks":[]}',
                encoding="utf8",
            )
            with self.assertRaisesRegex(GuidMappingError, "duplicate JSON key"):
                load_observations(duplicate_json)

    def test_write_is_atomic_and_refuses_input_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mapping = self._write_mapping(root)
            observations = self._write_observations(root)
            output = root / "corroboration.json"

            record = write_corroboration_record(mapping, observations, output)
            self.assertEqual(json.loads(output.read_text(encoding="utf8")), record)
            self.assertEqual(list(root.glob(".corroboration.json.*.tmp")), [])

            with self.assertRaisesRegex(GuidMappingError, "must not overwrite either input"):
                write_corroboration_record(mapping, observations, mapping)
            with self.assertRaisesRegex(GuidMappingError, "must not overwrite either input"):
                write_corroboration_record(mapping, observations, observations)


if __name__ == "__main__":
    unittest.main()
