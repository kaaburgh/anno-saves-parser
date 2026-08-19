import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from guid_mapping import validate_guid_mapping
from guid_mapping_export import (
    GuidMappingExportError,
    _atomic_write_text,
    _parse_input_hashes,
    _validate_output_path,
    build_mapping_document,
)


class FakeText:
    def __init__(self, values):
        self.values = values


class FakeAsset:
    def __init__(self, guid, name="", text=None):
        self.guid = guid
        self.name = name
        self.text = text


class GuidMappingExportTests(unittest.TestCase):
    def build(self, assets, **overrides):
        params = {
            "language": "english",
            "source_version": "anno-build-1",
            "source_hash": "sha256:" + "a" * 64,
            "mapping_version": "guid-map-1",
            "extractor_identity": "anno-mods/asset-extractor@3.0",
            "extractor_artifact_hash": "sha256:" + "b" * 64,
            "converter_identity": "anno-saves-parser/guid_mapping_export.py@test",
            "converter_artifact_hash": "sha256:" + "c" * 64,
            "input_hashes": {
                "assets": "sha256:" + "d" * 64,
                "localization-en": "sha256:" + "e" * 64,
            },
        }
        params.update(overrides)
        return build_mapping_document(assets, **params)

    def test_prefers_requested_localized_text_and_sorts_guids(self):
        document = self.build(
            [
                FakeAsset(2002, "InternalFactory", FakeText({"english": "Factory"})),
                FakeAsset(1001, "InternalResidence", FakeText({"english": "Residence"})),
            ]
        )
        self.assertEqual(
            document["entries"],
            {"1001": "Residence", "2002": "Factory"},
        )
        validated = validate_guid_mapping(document)
        self.assertEqual(validated["entries"][1001], "Residence")
        self.assertEqual(
            validated["provenance"]["source"],
            "operator-owned-anno1800-installation",
        )

    def test_structured_provenance_is_emitted(self):
        document = self.build([FakeAsset(1001, "Residence")])
        provenance = document["provenance"]
        self.assertEqual(
            provenance["extractor"]["identity"],
            "anno-mods/asset-extractor@3.0",
        )
        self.assertEqual(
            provenance["converter"]["identity"],
            "anno-saves-parser/guid_mapping_export.py@test",
        )
        self.assertEqual(
            list(provenance["input_hashes"]),
            ["assets", "localization-en"],
        )
        validated = validate_guid_mapping(document)
        self.assertEqual(
            validated["provenance"]["input_hashes"]["assets"],
            "sha256:" + "d" * 64,
        )

    def test_structured_provenance_can_be_omitted_for_schema_v1_compatibility(self):
        document = self.build(
            [FakeAsset(1001, "Residence")],
            extractor_identity=None,
            extractor_artifact_hash=None,
            converter_identity=None,
            converter_artifact_hash=None,
            input_hashes=None,
        )
        self.assertNotIn("extractor", document["provenance"])
        self.assertNotIn("converter", document["provenance"])
        self.assertNotIn("input_hashes", document["provenance"])
        validate_guid_mapping(document)

    def test_falls_back_to_asset_name_when_localized_text_is_missing(self):
        document = self.build(
            [FakeAsset(1001, "InternalName", FakeText({"german": "Deutscher Name"}))]
        )
        self.assertEqual(document["entries"]["1001"], "InternalName")

    def test_skips_assets_without_any_name(self):
        document = self.build(
            [FakeAsset(1001, ""), FakeAsset(2002, "Named")]
        )
        self.assertEqual(document["entries"], {"2002": "Named"})

    def test_rejects_conflicting_duplicate_guid(self):
        with self.assertRaises(GuidMappingExportError):
            self.build([FakeAsset(1001, "First"), FakeAsset(1001, "Second")])

    def test_rejects_empty_result(self):
        with self.assertRaises(GuidMappingExportError):
            self.build([FakeAsset(1001, "")])

    def test_rejects_invalid_source_hash(self):
        with self.assertRaises(GuidMappingExportError):
            self.build([FakeAsset(1001, "Name")], source_hash="sha256:not-a-digest")

    def test_rejects_invalid_structured_hashes(self):
        with self.assertRaisesRegex(GuidMappingExportError, "extractor_artifact_hash"):
            self.build(
                [FakeAsset(1001, "Name")],
                extractor_artifact_hash="sha256:not-a-digest",
            )
        with self.assertRaisesRegex(GuidMappingExportError, "input_hashes"):
            self.build(
                [FakeAsset(1001, "Name")],
                input_hashes={"assets": "sha256:not-a-digest"},
            )

    def test_rejects_artifact_hash_without_identity(self):
        with self.assertRaisesRegex(GuidMappingExportError, "requires extractor_identity"):
            self.build(
                [FakeAsset(1001, "Name")],
                extractor_identity=None,
            )

    def test_parse_input_hashes_rejects_duplicates_and_normalizes_hashes(self):
        parsed = _parse_input_hashes(
            [
                "assets=sha256:" + "A" * 64,
                "localization-en=sha256:" + "b" * 64,
            ]
        )
        self.assertEqual(parsed["assets"], "sha256:" + "a" * 64)
        with self.assertRaisesRegex(GuidMappingExportError, "duplicate"):
            _parse_input_hashes(
                [
                    "assets=sha256:" + "a" * 64,
                    "assets=sha256:" + "b" * 64,
                ]
            )

    def test_rejects_non_uint32_guid(self):
        with self.assertRaises(GuidMappingExportError):
            self.build([FakeAsset(0x1_0000_0000, "Too Large")])

    def test_output_must_not_overwrite_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            config_path.write_text("{}", encoding="utf8")
            extractor_root = root / "extractor"
            extractor_root.mkdir()
            config = SimpleNamespace(
                game_path=root / "game",
                cache_path=root / "cache",
                assetbrowser_dir=root / "assetbrowser",
            )
            with self.assertRaisesRegex(GuidMappingExportError, "must not overwrite"):
                _validate_output_path(
                    config_path,
                    config_path=config_path,
                    extractor_root=extractor_root,
                    config=config,
                )

    def test_output_must_be_outside_protected_source_trees(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            config_path.write_text("{}", encoding="utf8")
            extractor_root = root / "extractor"
            extractor_root.mkdir()
            config = SimpleNamespace(
                game_path=root / "game",
                cache_path=root / "cache",
                assetbrowser_dir=root / "assetbrowser",
            )
            protected_roots = [
                extractor_root,
                config.game_path,
                config.cache_path,
                config.assetbrowser_dir,
            ]
            for protected_root in protected_roots:
                protected_root.mkdir(exist_ok=True)
                with self.subTest(protected_root=protected_root):
                    with self.assertRaisesRegex(GuidMappingExportError, "outside protected"):
                        _validate_output_path(
                            protected_root / "mapping.json",
                            config_path=config_path,
                            extractor_root=extractor_root,
                            config=config,
                        )

    def test_output_path_is_resolved_when_safe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            extractor_root = root / "extractor"
            extractor_root.mkdir()
            config = SimpleNamespace(
                game_path=root / "game",
                cache_path=root / "cache",
                assetbrowser_dir=root / "assetbrowser",
            )
            output = root / "output" / "mapping.json"
            validated = _validate_output_path(
                output,
                config_path=root / "config.json",
                extractor_root=extractor_root,
                config=config,
            )
            self.assertEqual(validated, output.resolve())

    def test_atomic_write_replaces_output_without_temp_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "mapping.json"
            output.write_text("old", encoding="utf8")
            _atomic_write_text(output, "new\n")
            self.assertEqual(output.read_text(encoding="utf8"), "new\n")
            self.assertEqual(list(root.glob(".mapping.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
