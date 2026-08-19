"""Dependency-free provenance-aware GUID/name mapping support.

This module is intentionally separate from the canonical save parser. Numeric GUIDs
remain the canonical identity; human-readable names are optional derived evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

GUID_MAPPING_SCHEMA = "anno-saves-parser/guid-name-mapping"
GUID_MAPPING_SCHEMA_VERSION = 1
_MAX_GUID = 0xFFFFFFFF
_SHA256_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
_PROVENANCE_KEYS = {
    "source",
    "source_version",
    "mapping_version",
    "source_hash",
    "extractor",
    "converter",
    "input_hashes",
}
_PRODUCER_KEYS = {"identity", "artifact_hash"}


class GuidMappingError(ValueError):
    """Raised when a GUID mapping is malformed or provenance-incompatible."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise GuidMappingError(f"duplicate JSON key: {key!r}")
        out[key] = value
    return out


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GuidMappingError(f"{field} must be a non-empty string")
    return value


def _require_sha256(value: Any, field: str) -> str:
    digest = _require_nonempty_string(value, field)
    if _SHA256_RE.fullmatch(digest) is None:
        raise GuidMappingError(f"{field} must be sha256:<64 hex characters>")
    return digest.lower()


def _normalize_producer(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise GuidMappingError(f"{field} must be a JSON object")
    unknown = sorted(set(value) - _PRODUCER_KEYS)
    if unknown:
        raise GuidMappingError(f"unsupported {field} field(s): {', '.join(unknown)}")
    normalized = {
        "identity": _require_nonempty_string(value.get("identity"), f"{field}.identity")
    }
    if "artifact_hash" in value:
        normalized["artifact_hash"] = _require_sha256(
            value["artifact_hash"], f"{field}.artifact_hash"
        )
    return normalized


def _normalize_input_hashes(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise GuidMappingError("provenance.input_hashes must be a non-empty JSON object")
    normalized: dict[str, str] = {}
    for raw_label, raw_hash in value.items():
        label = _require_nonempty_string(raw_label, "provenance.input_hashes key")
        if label in normalized:
            raise GuidMappingError(f"duplicate provenance input label: {label!r}")
        normalized[label] = _require_sha256(
            raw_hash, f"provenance.input_hashes[{label!r}]"
        )
    return {label: normalized[label] for label in sorted(normalized)}


def _mapping_content_hash(
    provenance: dict[str, Any], entries: dict[int, str]
) -> str:
    """Return a stable content identity for all recognized semantic inputs."""
    material_document = {
        "schema": GUID_MAPPING_SCHEMA,
        "schema_version": GUID_MAPPING_SCHEMA_VERSION,
        "provenance": provenance,
        "entries": {str(guid): entries[guid] for guid in sorted(entries)},
    }
    encoded = json.dumps(
        material_document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def validate_guid_mapping(document: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize one mapping document.

    Returned ``entries`` are keyed by integer GUID for exact lookup. The returned
    provenance block is safe to attach to derived output; it contains no source
    asset payloads and includes a digest of every recognized mapping field that can
    affect interpretation.
    """
    if not isinstance(document, dict):
        raise GuidMappingError("mapping document must be a JSON object")
    if document.get("schema") != GUID_MAPPING_SCHEMA:
        raise GuidMappingError(f"unsupported GUID mapping schema: {document.get('schema')!r}")
    if document.get("schema_version") != GUID_MAPPING_SCHEMA_VERSION:
        raise GuidMappingError(
            "unsupported GUID mapping schema version: "
            f"{document.get('schema_version')!r}"
        )

    provenance = document.get("provenance")
    if not isinstance(provenance, dict):
        raise GuidMappingError("provenance must be a JSON object")
    unknown_provenance = sorted(set(provenance) - _PROVENANCE_KEYS)
    if unknown_provenance:
        raise GuidMappingError(
            "unsupported provenance field(s): " + ", ".join(unknown_provenance)
        )

    normalized_provenance: dict[str, Any] = {
        "source": _require_nonempty_string(provenance.get("source"), "provenance.source"),
        "source_version": _require_nonempty_string(
            provenance.get("source_version"), "provenance.source_version"
        ),
        "mapping_version": _require_nonempty_string(
            provenance.get("mapping_version"), "provenance.mapping_version"
        ),
    }
    if "source_hash" in provenance:
        normalized_provenance["source_hash"] = _require_nonempty_string(
            provenance["source_hash"], "provenance.source_hash"
        )
    if "extractor" in provenance:
        normalized_provenance["extractor"] = _normalize_producer(
            provenance["extractor"], "provenance.extractor"
        )
    if "converter" in provenance:
        normalized_provenance["converter"] = _normalize_producer(
            provenance["converter"], "provenance.converter"
        )
    if "input_hashes" in provenance:
        normalized_provenance["input_hashes"] = _normalize_input_hashes(
            provenance["input_hashes"]
        )

    raw_entries = document.get("entries")
    if not isinstance(raw_entries, dict):
        raise GuidMappingError("entries must be a JSON object keyed by decimal GUID")
    entries: dict[int, str] = {}
    for raw_guid, raw_name in raw_entries.items():
        if not isinstance(raw_guid, str) or not raw_guid.isdecimal():
            raise GuidMappingError(f"GUID key must be an unsigned decimal string: {raw_guid!r}")
        guid = int(raw_guid, 10)
        if guid < 0 or guid > _MAX_GUID:
            raise GuidMappingError(f"GUID is outside uint32 range: {raw_guid!r}")
        name = _require_nonempty_string(raw_name, f"entries[{raw_guid!r}]")
        if guid in entries:
            raise GuidMappingError(f"duplicate normalized GUID: {guid}")
        entries[guid] = name

    normalized_provenance["mapping_content_hash"] = _mapping_content_hash(
        normalized_provenance, entries
    )
    return {
        "schema": GUID_MAPPING_SCHEMA,
        "schema_version": GUID_MAPPING_SCHEMA_VERSION,
        "provenance": normalized_provenance,
        "entries": entries,
    }


def load_guid_mapping(path: Path) -> dict[str, Any]:
    """Load a UTF-8 JSON mapping and fail closed on malformed provenance/content."""
    try:
        with path.open("r", encoding="utf8") as stream:
            document = json.load(stream, object_pairs_hook=_reject_duplicate_keys)
    except UnicodeDecodeError as exc:
        raise GuidMappingError(f"GUID mapping is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GuidMappingError(f"invalid GUID mapping JSON: {exc}") from exc
    return validate_guid_mapping(document)


def resolve_guid(mapping: dict[str, Any], guid: int | None) -> str | None:
    """Resolve an exact GUID or return ``None``; never guess a nearby identity."""
    if guid is None:
        return None
    if not isinstance(guid, int) or isinstance(guid, bool) or guid < 0 or guid > _MAX_GUID:
        raise GuidMappingError(f"GUID lookup must be a uint32 integer or None: {guid!r}")
    return mapping["entries"].get(guid)


def enrich_structural_diff(diff: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a raw structural diff annotated with exact GUID names.

    The raw numeric GUID fields remain untouched. Every top-level event dictionary
    with ``guid`` and/or ``from_guid``/``to_guid`` fields receives the corresponding
    parallel name field, so enrichment follows producer content rather than a
    hardcoded list of structural-diff section names.
    """
    out = copy.deepcopy(diff)
    out["guid_mapping"] = {
        "schema": mapping["schema"],
        "schema_version": mapping["schema_version"],
        "provenance": copy.deepcopy(mapping["provenance"]),
    }
    for section in out.values():
        if not isinstance(section, list):
            continue
        for event in section:
            if not isinstance(event, dict):
                continue
            if "guid" in event:
                event["guid_name"] = resolve_guid(mapping, event.get("guid"))
            if "from_guid" in event:
                event["from_guid_name"] = resolve_guid(mapping, event.get("from_guid"))
            if "to_guid" in event:
                event["to_guid_name"] = resolve_guid(mapping, event.get("to_guid"))
    return out
