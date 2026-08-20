"""Verify representative GUID/name checks against one exact mapping.

This operator-side tool consumes observations obtained from a reference that the
operator asserts is independent of the mapping derivation. It verifies exact
agreement and packages a small corroboration record; it does not prove that the
reference itself is independent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from guid_mapping import GuidMappingError, validate_guid_mapping

OBSERVATIONS_SCHEMA = "anno-saves-parser/guid-mapping-corroboration-observations"
OBSERVATIONS_SCHEMA_VERSION = 1
CORROBORATION_SCHEMA = "anno-saves-parser/guid-mapping-corroboration"
CORROBORATION_SCHEMA_VERSION = 1

_TOP_LEVEL_KEYS = {"schema", "schema_version", "reference", "checks"}
_REFERENCE_KEYS = {"identity", "version", "artifact_hash"}
_CHECK_KEYS = {"guid", "name", "locator"}
_MAX_GUID = 0xFFFFFFFF


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise GuidMappingError(f"duplicate JSON key: {key!r}")
        out[key] = value
    return out


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GuidMappingError(f"{field} must be a non-empty string")
    return value.strip()


def _sha256(value: Any, field: str) -> str:
    digest = _nonempty_string(value, field)
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise GuidMappingError(f"{field} must be sha256:<64 hex characters>")
    try:
        int(digest[7:], 16)
    except ValueError as exc:
        raise GuidMappingError(f"{field} must be sha256:<64 hex characters>") from exc
    return digest.lower()


def _load_json_bytes(path: Path, *, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GuidMappingError(f"cannot read {label}: {exc}") from exc
    try:
        document = json.loads(raw.decode("utf8"), object_pairs_hook=_reject_duplicate_keys)
    except UnicodeDecodeError as exc:
        raise GuidMappingError(f"{label} is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GuidMappingError(f"invalid {label} JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise GuidMappingError(f"{label} must be a JSON object")
    return raw, document


def load_observations(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw, document = _load_json_bytes(path, label="corroboration observations")
    unknown = sorted(set(document) - _TOP_LEVEL_KEYS)
    if unknown:
        raise GuidMappingError("unsupported observation field(s): " + ", ".join(unknown))
    if document.get("schema") != OBSERVATIONS_SCHEMA:
        raise GuidMappingError(f"unsupported observation schema: {document.get('schema')!r}")
    if document.get("schema_version") != OBSERVATIONS_SCHEMA_VERSION:
        raise GuidMappingError(
            f"unsupported observation schema version: {document.get('schema_version')!r}"
        )

    raw_reference = document.get("reference")
    if not isinstance(raw_reference, dict):
        raise GuidMappingError("reference must be a JSON object")
    unknown_reference = sorted(set(raw_reference) - _REFERENCE_KEYS)
    if unknown_reference:
        raise GuidMappingError(
            "unsupported reference field(s): " + ", ".join(unknown_reference)
        )
    reference = {
        "identity": _nonempty_string(raw_reference.get("identity"), "reference.identity"),
        "version": _nonempty_string(raw_reference.get("version"), "reference.version"),
    }
    if "artifact_hash" in raw_reference:
        reference["artifact_hash"] = _sha256(
            raw_reference["artifact_hash"], "reference.artifact_hash"
        )

    raw_checks = document.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        raise GuidMappingError("checks must be a non-empty JSON array")
    checks: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, raw_check in enumerate(raw_checks):
        field = f"checks[{index}]"
        if not isinstance(raw_check, dict):
            raise GuidMappingError(f"{field} must be a JSON object")
        unknown_check = sorted(set(raw_check) - _CHECK_KEYS)
        if unknown_check:
            raise GuidMappingError(
                f"unsupported {field} field(s): " + ", ".join(unknown_check)
            )
        guid = raw_check.get("guid")
        if not isinstance(guid, int) or isinstance(guid, bool) or not 0 <= guid <= _MAX_GUID:
            raise GuidMappingError(f"{field}.guid must be a uint32 integer")
        if guid in seen:
            raise GuidMappingError(f"duplicate corroboration GUID: {guid}")
        seen.add(guid)
        check = {
            "guid": guid,
            "name": _nonempty_string(raw_check.get("name"), f"{field}.name"),
        }
        if "locator" in raw_check:
            check["locator"] = _nonempty_string(raw_check["locator"], f"{field}.locator")
        checks.append(check)

    checks.sort(key=lambda item: item["guid"])
    return raw, {"reference": reference, "checks": checks}


def build_corroboration_record(
    mapping_path: Path,
    observations_path: Path,
) -> dict[str, Any]:
    mapping_resolved = mapping_path.resolve()
    observations_resolved = observations_path.resolve()
    if mapping_resolved == observations_resolved:
        raise GuidMappingError("mapping and corroboration observations must be separate files")

    mapping_raw, mapping_document = _load_json_bytes(mapping_resolved, label="GUID mapping")
    mapping = validate_guid_mapping(mapping_document)
    observations_raw, observations = load_observations(observations_resolved)

    checked: list[dict[str, Any]] = []
    for check in observations["checks"]:
        guid = check["guid"]
        expected_name = check["name"]
        actual_name = mapping["entries"].get(guid)
        if actual_name is None:
            raise GuidMappingError(f"corroboration GUID {guid} is absent from the mapping")
        if actual_name != expected_name:
            raise GuidMappingError(
                f"corroboration mismatch for GUID {guid}: "
                f"mapping={actual_name!r} reference={expected_name!r}"
            )
        checked.append(dict(check))

    return {
        "schema": CORROBORATION_SCHEMA,
        "schema_version": CORROBORATION_SCHEMA_VERSION,
        "scope": "representative-guid-name-corroboration",
        "mapping": {
            "file_sha256": f"sha256:{hashlib.sha256(mapping_raw).hexdigest()}",
            "mapping_content_hash": mapping["provenance"]["mapping_content_hash"],
        },
        "observations": {
            "file_sha256": f"sha256:{hashlib.sha256(observations_raw).hexdigest()}",
            "reference": observations["reference"],
        },
        "independence": {
            "status": "operator-asserted-independent-reference",
            "note": (
                "This tool verifies exact agreement and provenance binding; "
                "it cannot prove that the supplied reference is independent."
            ),
        },
        "result": {"status": "matched", "check_count": len(checked)},
        "checks": checked,
    }


def write_corroboration_record(
    mapping_path: Path,
    observations_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    mapping_resolved = mapping_path.resolve()
    observations_resolved = observations_path.resolve()
    output_resolved = output_path.resolve()
    if output_resolved in {mapping_resolved, observations_resolved}:
        raise GuidMappingError("corroboration output must not overwrite either input")

    record = build_corroboration_record(mapping_resolved, observations_resolved)
    output_resolved.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf8",
            newline="\n",
            dir=output_resolved.parent,
            prefix=f".{output_resolved.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            json.dump(record, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temp_path, output_resolved)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return record


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify representative independently observed GUID/name pairs "
            "against one exact exported mapping."
        )
    )
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        record = write_corroboration_record(
            args.mapping,
            args.observations,
            args.output,
        )
    except GuidMappingError as exc:
        raise SystemExit(f"GUID mapping corroboration failed: {exc}") from exc
    print(
        "GUID mapping corroboration: "
        f"{record['result']['check_count']} representative checks matched"
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
