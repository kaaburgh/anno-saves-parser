"""Dependency-free provenance-aware GUID/name mapping support.

This module is intentionally separate from the canonical save parser. Numeric GUIDs
remain the canonical identity; human-readable names are optional derived evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

GUID_MAPPING_SCHEMA = "anno-saves-parser/guid-name-mapping"
GUID_MAPPING_SCHEMA_VERSION = 1
_MAX_GUID = 0xFFFFFFFF


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


def _mapping_content_hash(
    provenance: dict[str, str], entries: dict[int, str]
) -> str:
    """Return a stable content identity for all fields that affect resolution."""
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
    asset payloads and includes a digest of every mapping field that affects name
    resolution.
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
    normalized_provenance = {
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

    The raw numeric GUID fields remain untouched. Every GUID-bearing event receives
    a parallel name field whose value is ``None`` when the mapping has no exact
    entry, making unresolved identities explicit rather than heuristic.
    """
    out = copy.deepcopy(diff)
    out["guid_mapping"] = {
        "schema": mapping["schema"],
        "schema_version": mapping["schema_version"],
        "provenance": copy.deepcopy(mapping["provenance"]),
    }
    for section in ("added", "removed", "moved", "component_changed", "direction_changed"):
        for event in out.get(section, []):
            event["guid_name"] = resolve_guid(mapping, event.get("guid"))
    for event in out.get("guid_changed", []):
        event["from_guid_name"] = resolve_guid(mapping, event.get("from_guid"))
        event["to_guid_name"] = resolve_guid(mapping, event.get("to_guid"))
    return out
