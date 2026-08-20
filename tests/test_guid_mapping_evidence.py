from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from guid_mapping import GuidMappingError
from guid_mapping_evidence import (
    EVIDENCE_SCHEMA,
    build_evidence_record,
    write_evidence_record,
)


class GuidMappingEvidenceTests(unittest.TestCase):
    def _mapping_document(self, *, structured: bool = True) -> dict[str, object]:
        provenance: dict[str, object] = {
            "source": "operator-owned Anno 1800 installation",
            "source_version": "game-build-1",
            "mapping_version": "guid-map-test",
            "source_hash": "sha256:" + "a" * 64,
        }
        if structured:
            provenance.update(
                {
                    "extractor": {
                        "identity": "anno-mods/asset-extractor@3.0",
                        "artifact_hash": "sha256:" + "b" * 64,
                    },
                    "converter": {
                        "identity": "anno-saves-parser/guid_mapping_export.py@test",
                        "artifact_hash": "sha256:" + "c" * 64,
                    },
                    "input_hashes": {
                        "assets": "sha256:" + "d" * 64,
                        "localization-en": "sha256:" + "e" * 64,
                    },
                }
            )
        return {
            "schema": "anno-saves-parser/guid-name-mapping",
            "schema_version": 1,
            "provenance": provenance,
            "entries": {"100": "Warehouse", "200": "Marketplace"},
        }

    def _write_mapping(self, root: Path, *, structured: bool = True) -> Path:
        path = root / "mapping.json"
        path.write_text(
            json.dumps(self._mapping_document(structured=structured), sort_keys=True) + "\n",
            encoding="utf8",
        )
        return path

    def test_record_is_safe_deterministic_projection_of_exact_mapping_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mapping_path = self._write_mapping(root)
            raw = mapping_path.read_bytes()

            record = build_evidence_record(mapping_path)

            self.assertEqual(record["schema"], EVIDENCE_SCHEMA)
            self.assertEqual(record["scope"], "mapping-provenance-preflight")
            self.assertEqual(record["mapping"]["entry_count"], 2)
            self.assertEqual(
                record["mapping"]["file_sha256"],
                "sha256:" + hashlib.sha256(raw).hexdigest(),
            )
            self.assertEqual(
                record["independent_corroboration"]["status"],
                "required-not-recorded",
            )
            serialized = json.dumps(record, sort_keys=True)
            self.assertNotIn("Warehouse", serialized)
            self.assertNotIn("Marketplace", serialized)
            self.assertNotIn('"entries"', serialized)
            self.assertEqual(record, build_evidence_record(mapping_path))

    def test_legacy_mapping_remains_consumer_compatible_but_fails_real_evidence_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mapping_path = self._write_mapping(Path(temp_dir), structured=False)
            with self.assertRaisesRegex(
                GuidMappingError,
                "requires structured provenance field.*extractor, converter, input_hashes",
            ):
                build_evidence_record(mapping_path)

    def test_each_structured_real_run_provenance_field_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for missing in ("extractor", "converter", "input_hashes"):
                with self.subTest(missing=missing):
                    document = self._mapping_document()
                    del document["provenance"][missing]
                    path = root / f"missing-{missing}.json"
                    path.write_text(json.dumps(document), encoding="utf8")
                    with self.assertRaisesRegex(GuidMappingError, missing):
                        build_evidence_record(path)

    def test_write_is_atomic_projection_and_refuses_mapping_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mapping_path = self._write_mapping(root)
            output = root / "evidence" / "manifest.json"
            output.parent.mkdir()
            output.write_text("stale\n", encoding="utf8")

            record = write_evidence_record(mapping_path, output)

            self.assertEqual(json.loads(output.read_text(encoding="utf8")), record)
            self.assertEqual(list(output.parent.glob(".manifest.json.*.tmp")), [])
            with self.assertRaisesRegex(GuidMappingError, "must not overwrite"):
                write_evidence_record(mapping_path, mapping_path)

    def test_duplicate_mapping_keys_fail_closed_before_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mapping.json"
            path.write_text(
                '{"schema":"anno-saves-parser/guid-name-mapping",'
                '"schema":"duplicate","schema_version":1,"provenance":{},"entries":{}}',
                encoding="utf8",
            )
            with self.assertRaisesRegex(GuidMappingError, "duplicate JSON key"):
                build_evidence_record(path)


if __name__ == "__main__":
    unittest.main()
