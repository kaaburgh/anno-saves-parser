"""Build a compact provenance preflight record for one GUID mapping.

This operator-side tool validates the exact mapping bytes it hashes, requires the
structured producer/input provenance expected for a new real-data evidence run,
and emits no GUID/name entries. Independent corroboration remains a separate
required evidence step.
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

EVIDENCE_SCHEMA = "anno-saves-parser/guid-mapping-evidence"
EVIDENCE_SCHEMA_VERSION = 1


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise GuidMappingError(f"duplicate JSON key: {key!r}")
        out[key] = value
    return out


def _load_exact_mapping_bytes(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GuidMappingError(f"cannot read GUID mapping: {exc}") from exc
    try:
        text = raw.decode("utf8")
    except UnicodeDecodeError as exc:
        raise GuidMappingError(f"GUID mapping is not valid UTF-8: {exc}") from exc
    try:
        document = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise GuidMappingError(f"invalid GUID mapping JSON: {exc}") from exc
    return raw, validate_guid_mapping(document)


def build_evidence_record(mapping_path: Path) -> dict[str, Any]:
    """Return a safe manifest proving the mapping has real-run provenance fields."""
    raw, mapping = _load_exact_mapping_bytes(mapping_path)
    provenance = mapping["provenance"]
    required = ("extractor", "converter", "input_hashes")
    missing = [field for field in required if field not in provenance]
    if missing:
        raise GuidMappingError(
            "real-evidence preflight requires structured provenance field(s): "
            + ", ".join(missing)
        )

    safe_provenance = {
        "source": provenance["source"],
        "source_version": provenance["source_version"],
        "mapping_version": provenance["mapping_version"],
        "extractor": provenance["extractor"],
        "converter": provenance["converter"],
        "input_hashes": provenance["input_hashes"],
    }
    if "source_hash" in provenance:
        safe_provenance["source_hash"] = provenance["source_hash"]

    return {
        "schema": EVIDENCE_SCHEMA,
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "scope": "mapping-provenance-preflight",
        "mapping": {
            "schema": mapping["schema"],
            "schema_version": mapping["schema_version"],
            "file_sha256": f"sha256:{hashlib.sha256(raw).hexdigest()}",
            "mapping_content_hash": provenance["mapping_content_hash"],
            "entry_count": len(mapping["entries"]),
        },
        "provenance": safe_provenance,
        "independent_corroboration": {"status": "required-not-recorded"},
    }


def write_evidence_record(mapping_path: Path, output_path: Path) -> dict[str, Any]:
    mapping_resolved = mapping_path.resolve()
    output_resolved = output_path.resolve()
    if mapping_resolved == output_resolved:
        raise GuidMappingError("evidence output must not overwrite the GUID mapping")

    record = build_evidence_record(mapping_resolved)
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
        description="Validate real-run GUID mapping provenance and emit a safe preflight manifest."
    )
    parser.add_argument("--mapping", type=Path, required=True, help="GUID mapping JSON to validate")
    parser.add_argument("--output", type=Path, required=True, help="Evidence manifest JSON to write")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        record = write_evidence_record(args.mapping, args.output)
    except GuidMappingError as exc:
        raise SystemExit(f"GUID mapping evidence preflight failed: {exc}") from exc
    print(
        "GUID mapping evidence preflight: "
        f"{record['mapping']['entry_count']} entries, "
        f"{record['mapping']['mapping_content_hash']}"
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
