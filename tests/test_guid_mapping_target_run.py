from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import guid_mapping_target_run as target_run


class GuidMappingTargetRunTests(unittest.TestCase):
    def _args(self, root: Path) -> argparse.Namespace:
        config = root / "config.json"
        observations = root / "observations.json"
        config.write_text('{"config": true}\n', encoding="utf8")
        observations.write_text('{"observations": true}\n', encoding="utf8")
        return argparse.Namespace(
            asset_extractor_root=root / "asset-extractor",
            config=config,
            observations=observations,
            output_dir=root / "evidence",
            runner_identity="anno-saves-parser/guid_mapping_target_run.py@test",
            stage_timeout_seconds=30,
            language="english",
            source_version="game-build-test",
            source_hash="sha256:" + "1" * 64,
            mapping_version="mapping-test",
            extractor_identity="anno-mods/asset-extractor@test",
            extractor_artifact_hash="sha256:" + "2" * 64,
            converter_identity="anno-saves-parser/guid_mapping_export.py@test",
            converter_artifact_hash="sha256:" + "3" * 64,
            input_hash=[
                "assets=sha256:" + "4" * 64,
                "localization-en=sha256:" + "5" * 64,
            ],
        )

    def _repo_root(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        for name in (
            "guid_mapping_export.py",
            "guid_mapping_evidence.py",
            "guid_mapping_corroboration.py",
        ):
            (repo / name).write_text("# synthetic tool\n", encoding="utf8")
        return repo

    def test_success_sequences_all_stages_and_writes_safe_run_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self._args(root)
            repo = self._repo_root(root)
            calls: list[list[str]] = []

            def fake_run(command, *, cwd, check, timeout):
                self.assertEqual(cwd, repo.resolve())
                self.assertFalse(check)
                calls.append(command)
                output = Path(command[command.index("--output") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(Path(command[1]).stem + "\n", encoding="utf8")
                return subprocess.CompletedProcess(command, 0)

            code, record = target_run.run_target_evidence(
                args, repo_root=repo, run_command=fake_run
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                [Path(command[1]).name for command in calls],
                [
                    "guid_mapping_export.py",
                    "guid_mapping_evidence.py",
                    "guid_mapping_corroboration.py",
                ],
            )
            export = calls[0]
            self.assertIn("--extractor-artifact-hash", export)
            self.assertEqual(export.count("--input-hash"), 2)
            self.assertEqual(record["result"], {"status": "success"})
            self.assertEqual(
                [stage["status"] for stage in record["stages"]],
                ["success", "success", "success"],
            )
            self.assertEqual(
                set(record["artifacts"]), {"export", "preflight", "corroboration"}
            )
            run_record_path = args.output_dir / target_run.RUN_RECORD_NAME
            written = json.loads(run_record_path.read_text(encoding="utf8"))
            self.assertEqual(written, record)
            self.assertEqual(written["runner"]["identity"], args.runner_identity)
            self.assertNotIn(str(args.config.resolve()), json.dumps(written))
            self.assertNotIn(str(args.observations.resolve()), json.dumps(written))

    def test_failed_later_stage_stops_and_publishes_failure_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self._args(root)
            repo = self._repo_root(root)
            calls: list[str] = []

            def fake_run(command, *, cwd, check, timeout):
                name = Path(command[1]).name
                calls.append(name)
                if name == "guid_mapping_export.py":
                    output = Path(command[command.index("--output") + 1])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text("mapping\n", encoding="utf8")
                    return subprocess.CompletedProcess(command, 0)
                return subprocess.CompletedProcess(command, 7)

            code, record = target_run.run_target_evidence(
                args, repo_root=repo, run_command=fake_run
            )

            self.assertEqual(code, 7)
            self.assertEqual(
                calls, ["guid_mapping_export.py", "guid_mapping_evidence.py"]
            )
            self.assertEqual(
                record["result"], {"status": "failed", "failed_stage": "preflight"}
            )
            self.assertEqual(record["stages"][-1]["status"], "failed")
            self.assertTrue((args.output_dir / target_run.RUN_RECORD_NAME).is_file())
            self.assertFalse(
                (args.output_dir / target_run.CORROBORATION_NAME).exists()
            )

    def test_reused_output_dir_does_not_report_stale_downstream_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self._args(root)
            repo = self._repo_root(root)
            args.output_dir.mkdir(parents=True)
            (args.output_dir / target_run.EVIDENCE_NAME).write_text(
                "stale evidence\n", encoding="utf8"
            )
            (args.output_dir / target_run.CORROBORATION_NAME).write_text(
                "stale corroboration\n", encoding="utf8"
            )
            (args.output_dir / target_run.RUN_RECORD_NAME).write_text(
                '{"result": {"status": "stale"}}\n', encoding="utf8"
            )

            def fake_run(command, *, cwd, check, timeout):
                name = Path(command[1]).name
                if name == "guid_mapping_export.py":
                    output = Path(command[command.index("--output") + 1])
                    output.write_text("fresh mapping\n", encoding="utf8")
                    return subprocess.CompletedProcess(command, 0)
                return subprocess.CompletedProcess(command, 7)

            code, record = target_run.run_target_evidence(
                args, repo_root=repo, run_command=fake_run
            )

            self.assertEqual(code, 7)
            self.assertEqual(set(record["artifacts"]), {"export"})
            self.assertFalse((args.output_dir / target_run.EVIDENCE_NAME).exists())
            self.assertFalse((args.output_dir / target_run.CORROBORATION_NAME).exists())
            written = json.loads(
                (args.output_dir / target_run.RUN_RECORD_NAME).read_text(encoding="utf8")
            )
            self.assertEqual(written["result"], {"status": "failed", "failed_stage": "preflight"})
            self.assertEqual(set(written["artifacts"]), {"export"})

    def test_successful_stage_must_publish_its_current_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self._args(root)
            repo = self._repo_root(root)

            def fake_run(command, *, cwd, check, timeout):
                name = Path(command[1]).name
                if name == "guid_mapping_export.py":
                    output = Path(command[command.index("--output") + 1])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text("mapping\n", encoding="utf8")
                return subprocess.CompletedProcess(command, 0)

            code, record = target_run.run_target_evidence(
                args, repo_root=repo, run_command=fake_run
            )

            self.assertEqual(code, 2)
            self.assertEqual(record["result"], {"status": "failed", "failed_stage": "preflight"})
            self.assertEqual(record["stages"][-1], {"name": "preflight", "returncode": 2, "status": "failed"})
            self.assertEqual(set(record["artifacts"]), {"export"})

    def test_export_failure_does_not_write_before_output_safety_is_established(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self._args(root)
            repo = self._repo_root(root)

            def fake_run(command, *, cwd, check, timeout):
                return subprocess.CompletedProcess(command, 9)

            code, record = target_run.run_target_evidence(
                args, repo_root=repo, run_command=fake_run
            )

            self.assertEqual(code, 9)
            self.assertIsNone(record)
            self.assertFalse((args.output_dir / target_run.RUN_RECORD_NAME).exists())

    def test_observations_cannot_alias_generated_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self._args(root)
            args.output_dir.mkdir(parents=True)
            args.observations = args.output_dir / target_run.EVIDENCE_NAME
            args.observations.write_text("{}\n", encoding="utf8")
            repo = self._repo_root(root)

            with self.assertRaisesRegex(
                target_run.GuidMappingTargetRunError,
                "observations must be separate",
            ):
                target_run.run_target_evidence(args, repo_root=repo)


if __name__ == "__main__":
    unittest.main()
