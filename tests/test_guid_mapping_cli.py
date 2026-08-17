import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import anno_save_probe as probe


class GuidMappingCliTests(unittest.TestCase):
    @staticmethod
    def _state(name: str, buildings: list[dict]) -> dict:
        return {
            "schema": probe.CANONICAL_SCHEMA,
            "schema_version": probe.CANONICAL_SCHEMA_VERSION,
            "source": {"save_name": name},
            "sessions": [
                {
                    "session_guid": 1,
                    "session_id": 1,
                    "player_areas": [{"area_id": 10, "owner_id": 0}],
                    "buildings": buildings,
                }
            ],
        }

    @staticmethod
    def _mapping_document() -> dict:
        return {
            "schema": "anno-saves-parser/guid-name-mapping",
            "schema_version": 1,
            "provenance": {
                "source": "synthetic-test-source",
                "source_version": "fixture-v1",
                "mapping_version": "mapping-v1",
            },
            "entries": {"1001": "Synthetic Warehouse"},
        }

    def _run_main(self, argv: list[str], states: list[dict]) -> None:
        saves = [Path("before.a7s"), Path("after.a7s")]
        with (
            patch.object(probe, "discover_saves", return_value=saves),
            patch.object(probe, "parse_saves_batch", return_value=states),
            patch.object(probe, "report_worker_plan"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            probe.main(argv)

    def test_option_is_public_and_parsed_as_path(self):
        args = probe.parse_cli_args(["saves", "--guid-mapping", "mapping.json"])
        self.assertEqual(args.guid_mapping, Path("mapping.json"))
        self.assertIn("--guid-mapping", probe.build_arg_parser().format_help())

    def test_invalid_mapping_fails_before_save_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            mapping_path = Path(td) / "mapping.json"
            mapping_path.write_text("{not-json", encoding="utf8")
            stderr = io.StringIO()
            with (
                patch.object(probe, "discover_saves") as discover,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                probe.main(["saves", "--guid-mapping", str(mapping_path)])

        self.assertEqual(raised.exception.code, 2)
        discover.assert_not_called()
        self.assertIn("--guid-mapping", stderr.getvalue())
        self.assertIn("invalid GUID mapping JSON", stderr.getvalue())

    def test_invalid_utf8_mapping_fails_before_save_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            mapping_path = Path(td) / "mapping.json"
            mapping_path.write_bytes(b"\xff\xfe")
            stderr = io.StringIO()
            with (
                patch.object(probe, "discover_saves") as discover,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                probe.main(["saves", "--guid-mapping", str(mapping_path)])

        self.assertEqual(raised.exception.code, 2)
        discover.assert_not_called()
        self.assertIn("not valid UTF-8", stderr.getvalue())

    def test_cli_without_mapping_preserves_raw_diff_shape(self):
        states = [
            self._state("before.a7s", []),
            self._state(
                "after.a7s",
                [{"area_id": 10, "id": 7, "guid": 1001, "components": ["Warehouse"]}],
            ),
        ]
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "out"
            self._run_main(["before.a7s", "after.a7s", "-o", str(output)], states)
            summary = json.loads((output / "summary.json").read_text(encoding="utf8"))

        diff = summary["diffs"][0]
        self.assertEqual(diff["added"][0]["guid"], 1001)
        self.assertNotIn("guid_name", diff["added"][0])
        self.assertNotIn("guid_mapping", diff)

    def test_valid_mapping_enriches_summary_diff_only(self):
        states = [
            self._state("before.a7s", []),
            self._state(
                "after.a7s",
                [{"area_id": 10, "id": 7, "guid": 1001, "components": ["Warehouse"]}],
            ),
        ]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mapping_path = root / "mapping.json"
            mapping_path.write_text(
                json.dumps(self._mapping_document()),
                encoding="utf8",
            )
            output = root / "out"
            self._run_main(
                [
                    "before.a7s",
                    "after.a7s",
                    "--guid-mapping",
                    str(mapping_path),
                    "-o",
                    str(output),
                ],
                states,
            )
            summary = json.loads((output / "summary.json").read_text(encoding="utf8"))

        diff = summary["diffs"][0]
        self.assertEqual(diff["added"][0]["guid"], 1001)
        self.assertEqual(diff["added"][0]["guid_name"], "Synthetic Warehouse")
        self.assertEqual(diff["guid_mapping"]["provenance"]["source"], "synthetic-test-source")
        self.assertTrue(
            diff["guid_mapping"]["provenance"]["mapping_content_hash"].startswith("sha256:")
        )
        self.assertNotIn("guid_mapping", summary["states"][0])


if __name__ == "__main__":
    unittest.main()
