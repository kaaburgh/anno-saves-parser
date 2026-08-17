# GUID/name mapping provenance contract

Numeric GUIDs remain canonical identity in parser and structural-diff output. Human-readable names are optional derived evidence supplied by a separate mapping document; the core save parser does not download game assets, infer names from numeric patterns, or require a mapping to parse saves.

## Mapping schema v1

A mapping is UTF-8 JSON with schema `anno-saves-parser/guid-name-mapping`, schema version `1`, an explicit provenance block, and exact decimal uint32 GUID keys:

```json
{
  "schema": "anno-saves-parser/guid-name-mapping",
  "schema_version": 1,
  "provenance": {
    "source": "operator-owned-catalog-derivation",
    "source_version": "example-build-id",
    "mapping_version": "example-mapping-revision",
    "source_hash": "sha256:optional-source-identity"
  },
  "entries": {
    "1001": "Example name"
  }
}
```

`source`, `source_version`, and `mapping_version` are required non-empty strings. `source_hash` is optional, but when supplied it is preserved in derived output. The selected real-source path is documented in [`guid-source-selection.md`](./guid-source-selection.md): an operator-owned Anno 1800 installation is the primary evidence source, normalized through a pinned `anno-mods/asset-extractor` release or commit. The core parser still does not acquire or download proprietary source assets, and proprietary assets or extracted private catalogs must not be committed merely to populate names.

Validation also derives `provenance.mapping_content_hash`, a SHA-256 identity over a canonical serialization of every recognized mapping field that can affect GUID/name interpretation: schema/version, normalized provenance, and exact entries. It is generated rather than trusted from operator input. Changing a resolved name or other material mapping value therefore changes the attached identity even when human-readable source/mapping version labels are reused; irrelevant JSON formatting or entry order does not change it.

The loader fails closed on unsupported schema versions, missing provenance, duplicate JSON keys, non-decimal/out-of-range GUID keys, and empty names. Resolution is exact only. An absent entry yields `None`; no nearest-number, frequency, fuzzy, ordering, or other heuristic fallback is permitted.

## Structural-diff enrichment

`guid_mapping.enrich_structural_diff()` returns a copy of a raw structural diff. It leaves every numeric GUID untouched, adds a `guid_mapping` block containing mapping schema/provenance (including the generated `mapping_content_hash`), and adds parallel nullable name fields to GUID-bearing events (`guid_name`, or `from_guid_name` / `to_guid_name` for GUID transitions).

This keeps the evidence boundary explicit: a consumer can always distinguish observed numeric identity from human-readable mapping evidence, can see which mapping revision produced the names, and can bind those derived names to the immutable semantic content identity of that mapping. Canonical schema v1 is unchanged.

## Batch CLI integration

The public batch CLI accepts an optional operator-owned mapping path:

```text
python anno_save_probe.py SAVE_OR_DIRECTORY --guid-mapping path/to/mapping.json
```

The mapping document is loaded and validated once before save discovery and expensive parsing. An unreadable, malformed, or provenance-incompatible mapping is a command-line error; the parser does not silently continue with partially trusted names.

When `--guid-mapping` is omitted, CLI behavior and `summary.json` diff shape remain unchanged. When it is supplied, only the structural diffs embedded in `summary.json` are enriched through the exact-only mapping layer. Canonical snapshot files remain canonical schema v1 and are not annotated with names, while raw numeric GUID fields in enriched diffs remain unchanged alongside their parallel nullable name fields.

The CLI does not download or infer a real Anno mapping source. Source acquisition remains an explicit operator-owned step following [`guid-source-selection.md`](./guid-source-selection.md), outside parser execution.

## Current boundary

The repository now provides the deterministic mapping/validation/enrichment API, optional batch-CLI wiring with synthetic regression coverage, and a documented operator-owned real-source path. The converter/export step into mapping schema v1 and validation against operator-owned real data remain open under `ASP-P1-2`; no real Anno GUID/name claim is established by this repository yet.
