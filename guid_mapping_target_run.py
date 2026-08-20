"""Run the bounded operator-owned GUID mapping evidence workflow end to end."""
from __future__ import annotations
import argparse, hashlib, json, os, platform, subprocess, sys, tempfile
from pathlib import Path
from typing import Any

RUN_SCHEMA = "anno-saves-parser/guid-mapping-target-run"
RUN_SCHEMA_VERSION = 1
MAPPING_NAME = "guid-mapping.json"
EVIDENCE_NAME = "guid-mapping-evidence.json"
CORROBORATION_NAME = "guid-mapping-corroboration.json"
RUN_RECORD_NAME = "guid-mapping-target-run.json"

class GuidMappingTargetRunError(ValueError):
    pass

def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"

def _atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf8", newline="\n", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            json.dump(document, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

def _artifact(path: Path):
    if not path.is_file():
        return None
    return {"name": path.name, "sha256": _sha256_file(path)}

def _script(root: Path, name: str) -> str:
    path = (root / name).resolve()
    if not path.is_file():
        raise GuidMappingTargetRunError(f"required repository tool is missing: {name}")
    return str(path)

def _output_paths(output_dir: Path):
    root = output_dir.resolve()
    return {
        "mapping": root / MAPPING_NAME,
        "evidence": root / EVIDENCE_NAME,
        "corroboration": root / CORROBORATION_NAME,
        "run_record": root / RUN_RECORD_NAME,
    }

def _export_command(args, repo_root: Path, mapping: Path):
    command = [
        sys.executable, _script(repo_root, "guid_mapping_export.py"),
        "--asset-extractor-root", str(args.asset_extractor_root),
        "--config", str(args.config),
        "--output", str(mapping),
        "--language", args.language,
        "--source-version", args.source_version,
        "--source-hash", args.source_hash,
        "--mapping-version", args.mapping_version,
        "--extractor-identity", args.extractor_identity,
        "--converter-identity", args.converter_identity,
    ]
    if args.extractor_artifact_hash:
        command += ["--extractor-artifact-hash", args.extractor_artifact_hash]
    if args.converter_artifact_hash:
        command += ["--converter-artifact-hash", args.converter_artifact_hash]
    for value in args.input_hash:
        command += ["--input-hash", value]
    return command

def _stage_commands(args, repo_root: Path, outputs):
    return [
        ("export", _export_command(args, repo_root, outputs["mapping"])),
        ("preflight", [sys.executable, _script(repo_root, "guid_mapping_evidence.py"), "--mapping", str(outputs["mapping"]), "--output", str(outputs["evidence"])]),
        ("corroboration", [sys.executable, _script(repo_root, "guid_mapping_corroboration.py"), "--mapping", str(outputs["mapping"]), "--observations", str(args.observations), "--output", str(outputs["corroboration"])]),
    ]

def _base_record(args):
    return {
        "schema": RUN_SCHEMA,
        "schema_version": RUN_SCHEMA_VERSION,
        "scope": "operator-owned-guid-mapping-target-evidence",
        "runner": {"identity": args.runner_identity},
        "environment": {"python": platform.python_version(), "platform": platform.system(), "machine": platform.machine()},
        "inputs": {
            "config": {"sha256": _sha256_file(args.config.resolve())},
            "observations": {"sha256": _sha256_file(args.observations.resolve())},
        },
        "artifacts": {},
        "stages": [],
        "result": {"status": "running"},
    }

def _clear_stale_downstream_outputs(outputs) -> None:
    for key in ("evidence", "corroboration", "run_record"):
        outputs[key].unlink(missing_ok=True)

def run_target_evidence(args, *, repo_root=None, run_command=subprocess.run):
    root = (repo_root or Path(__file__).resolve().parent).resolve()
    outputs = _output_paths(args.output_dir)
    observations = args.observations.resolve()
    if observations in outputs.values():
        raise GuidMappingTargetRunError("observations must be separate from generated output artifacts")
    if not observations.is_file():
        raise GuidMappingTargetRunError(f"observations file does not exist: {observations}")
    if not args.config.resolve().is_file():
        raise GuidMappingTargetRunError(f"asset-extractor config does not exist: {args.config}")
    if not args.runner_identity.strip():
        raise GuidMappingTargetRunError("runner identity must be a non-empty string")
    if args.stage_timeout_seconds <= 0:
        raise GuidMappingTargetRunError("stage timeout must be greater than zero")

    commands = _stage_commands(args, root, outputs)
    record = None
    artifact_keys = {"export": "mapping", "preflight": "evidence", "corroboration": "corroboration"}

    for index, (stage_name, command) in enumerate(commands):
        try:
            completed = run_command(
                command,
                cwd=root,
                check=False,
                timeout=args.stage_timeout_seconds,
            )
            returncode = int(completed.returncode)
            timed_out = False
        except subprocess.TimeoutExpired:
            returncode = 124
            timed_out = True

        artifact_key = artifact_keys[stage_name]
        artifact = _artifact(outputs[artifact_key])
        if index == 0 and returncode == 0:
            if artifact is None:
                return 2, None
            _clear_stale_downstream_outputs(outputs)
            record = _base_record(args)
        elif record is not None and returncode == 0 and artifact is None:
            returncode = 2

        if record is not None:
            if artifact is not None:
                record["artifacts"][stage_name] = artifact
            record["stages"].append({
                "name": stage_name,
                "returncode": returncode,
                "status": "success" if returncode == 0 else ("timeout" if timed_out else "failed"),
            })
        if returncode != 0:
            if record is not None:
                record["result"] = {"status": "failed", "failed_stage": stage_name}
                _atomic_write_json(outputs["run_record"], record)
            return returncode, record

    record["result"] = {"status": "success"}
    _atomic_write_json(outputs["run_record"], record)
    return 0, record

def build_arg_parser():
    parser = argparse.ArgumentParser(description="Run export, provenance preflight, and representative corroboration as one bounded operator-owned GUID evidence workflow.")
    parser.add_argument("--asset-extractor-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--runner-identity", required=True)
    parser.add_argument("--stage-timeout-seconds", type=int, default=1800)
    parser.add_argument("--language", default="english")
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--source-hash", required=True)
    parser.add_argument("--mapping-version", required=True)
    parser.add_argument("--extractor-identity", required=True)
    parser.add_argument("--extractor-artifact-hash")
    parser.add_argument("--converter-identity", required=True)
    parser.add_argument("--converter-artifact-hash")
    parser.add_argument("--input-hash", action="append", default=[], metavar="LABEL=SHA256", required=True)
    return parser

def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    try:
        returncode, record = run_target_evidence(args)
    except (GuidMappingTargetRunError, OSError) as exc:
        print(f"GUID mapping target run failed before safe output was established: {exc}", file=sys.stderr)
        return 2
    if returncode != 0:
        failed_stage = record["result"]["failed_stage"] if record else "export"
        print(f"GUID mapping target run failed at stage: {failed_stage}", file=sys.stderr)
        return returncode
    print(f"GUID mapping target run completed; wrote {args.output_dir / RUN_RECORD_NAME}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
