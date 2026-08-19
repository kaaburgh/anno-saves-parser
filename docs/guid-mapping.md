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
    "source_hash": "sha256:optional-source-identity",
    "extractor": {
      "identity": "anno-mods/asset-extractor@3.0",
      "artifact_hash": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    },
    "converter": {
      "identity": "anno-saves-parser/guid_mapping_export.py@<commit>",
      "artifact_hash": "sha256:abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    },
    "input_hashes": {
      "assets": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
      "localization-en": "sha256:2222222222222222222222222222222222222222222222222222222222222222"
    }
  },
  "entries": {
    "1001": "Example name"
  }
}
```

`source`, `source_version`, and `mapping_version` are required non-empty strings. `source_hash` remains optional and preserves compatibility with existing schema-v1 mappings. `extractor`, `converter`, and `input_hashes` are optional structured provenance extensions within schema v1. Producer objects require an `identity` and may carry an `artifact_hash`; `input_hashes` maps stable logical input labels to exact SHA-256 identities. Structured SHA-256 fields use `sha256:<64 hex>` syntax. Existing schema-v1 mappings that omit all three structured fields remain valid.

The selected real-source path is documented in [`guid-source-selection.md`](./guid-source-selection.md): an operator-owned Anno 1800 installation is the primary evidence source, normalized through a pinned `anno-mods/asset-extractor` release or commit. The core parser still does not acquire or download proprietary source assets, and proprietary assets or extracted private catalogs must not be committed merely to populate names.

Validation derives `provenance.mapping_content_hash`, a SHA-256 identity over a canonical serialization of every recognized mapping field that can affect GUID/name interpretation: schema/version, normalized provenance, and exact entries. It is generated rather than trusted from operator input. Changing a resolved name, extractor/converter identity, producer artifact hash, or material input hash therefore changes the attached identity even when human-readable source/mapping version labels are reused; irrelevant JSON formatting and object/entry order do not change it.

The loader fails closed on unsupported schema versions, missing provenance, duplicate JSON keys, unknown provenance fields, unknown structured producer fields, malformed structured hashes, non-decimal/out-of-range GUID keys, and empty names. Unknown provenance is rejected rather than silently discarded. Resolution is exact only. An absent entry yields `None`; no nearest-number, frequency, fuzzy, ordering, or other heuristic fallback is permitted.

## Structural-diff enrichment

`guid_mapping.enrich_structural_diff()` returns a copy of a raw structural diff. It leaves every numeric GUID untouched, adds a `guid_mapping` block containing mapping schema/provenance (including the generated `mapping_content_hash` and any structured producer/input provenance), and adds parallel nullable name fields to GUID-bearing events (`guid_name`, or `from_guid_name` / `to_guid_name` for GUID transitions).

This keeps the evidence boundary explicit: a consumer can always distinguish observed numeric identity from human-readable mapping evidence, can see which mapping revision and machine-checkable producer/input identities produced the names, and can bind those derived names to the immutable semantic content identity of that mapping. Canonical schema v1 is unchanged.

## Batch CLI integration

The public batch CLI accepts an optional operator-owned mapping path:

```text
python anno_save_probe.py SAVE_OR_DIRECTORY --guid-mapping path/to/mapping.json
```

The mapping document is loaded and validated once before save discovery and expensive parsing. An unreadable, malformed, or provenance-incompatible mapping is a command-line error; the parser does not silently continue with partially trusted names.

When `--guid-mapping` is omitted, CLI behavior and `summary.json` diff shape remain unchanged. When it is supplied, only the structural diffs embedded in `summary.json` are enriched through the exact-only mapping layer. Canonical snapshot files remain canonical schema v1 and are not annotated with names, while raw numeric GUID fields in enriched diffs remain unchanged alongside their parallel nullable name fields.

The CLI does not download or infer a real Anno mapping source. Source acquisition remains an explicit operator-owned step following [`guid-source-selection.md`](./guid-source-selection.md), outside parser execution.

## Current boundary

The repository now provides the deterministic mapping/validation/enrichment API, optional batch-CLI wiring with synthetic regression coverage, a documented operator-owned real-source path, and `guid_mapping_export.py` as the deterministic operator-side exporter into mapping schema v1. Schema v1 can now preserve machine-checkable extractor/converter identities and per-input SHA-256 identities, and those fields participate in `mapping_content_hash` instead of being silently discarded. The remaining `ASP-P1-2` evidence step is an operator-owned real-data export with the required provenance plus independent corroboration of representative mappings; no real Anno GUID/name claim is established by this repository yet.
