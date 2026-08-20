# Canonical state schema v1

This document defines the normative downstream contract for per-save `*.canonical.json.gz` files identified by canonical schema version 1. The contract remains authoritative across parser releases while schema version 1 is current; `anno-saves-parser` 0.3.x and 0.4.x emit this schema.

## Identity

A canonical state document MUST contain:

```json
{
  "schema": "anno-saves-parser/canonical-state",
  "schema_version": 1,
  "source": {"save_name": "Synthetic Save.a7s"},
  "sessions": []
}
```

`schema` and `schema_version` identify this contract. `source.save_name` is source-file metadata only; it is not a stable in-game identity and may change if a save file is renamed.

## Fully synthetic example

```json
{
  "schema": "anno-saves-parser/canonical-state",
  "schema_version": 1,
  "source": {
    "save_name": "Synthetic Save.a7s"
  },
  "sessions": [
    {
      "session_guid": 123456,
      "session_id": 7,
      "map": "synthetic/session.a7t",
      "observed_areas": [
        {
          "area_id": 42,
          "owner_id": 0
        },
        {
          "area_id": 99,
          "owner_id": 3
        }
      ],
      "player_areas": [
        {
          "area_id": 42,
          "owner_id": 0,
          "city_name_guid": 700
        }
      ],
      "buildings": [
        {
          "area_id": 42,
          "id": 9001,
          "guid": 777001,
          "components": ["Building", "Warehouse"],
          "position": [10.5, 2.25, 30.75],
          "direction": 1.5
        }
      ]
    }
  ]
}
```

All values in this example are invented. It contains no derived data from a user save.

## Root fields

### `schema`

Required string. For v1 it is exactly `anno-saves-parser/canonical-state`.

### `schema_version`

Required integer. This document defines version `1`.

### `source`

Required object containing:

- `save_name` — required string containing the source save file name used for this export.

Source metadata is descriptive and is not part of stable game-object identity.

### `sessions`

Required array. Sessions are sorted deterministically by observed `session_guid`, then `session_id`, then `map`, with sessions lacking a GUID after sessions with an observed GUID. If those identity/descriptor values tie, the fully normalized canonical session content is used as a deterministic final tie-breaker. Raw extraction order is never a canonical ordering input; exact duplicate canonical sessions are indistinguishable and therefore order-equivalent.

## Session fields

Each session contains:

- `session_guid` — required unsigned 32-bit integer or `null`; explicit `null` preserves observed absence rather than inventing a value;
- `session_id` — required unsigned 32-bit integer or `null`;
- `map` — optional string containing the raw observed session-map path; no region or gameplay semantics are assigned by this field;
- `observed_areas` — optional array containing structurally observed area identities and supported ownership values, when this projection is available from the parser;
- `player_areas` — required array;
- `buildings` — required array.

The parser accepts these numeric descriptor fields only from their supported 4-byte little-endian representation. A zero-length or oversized representation is a parse error rather than a plausible integer.

## Observed-area fields

When `observed_areas` is present, each entry contains:

- `area_id` — required unsigned 32-bit integer from an observed `AreaInfo` / `AreaID` value;
- `owner_id` — optional unsigned 32-bit integer when a supported ownership value was observed for that same `AreaInfo` entry.

Entries are sorted by `area_id`. Duplicate observed `area_id` values within one canonical session are rejected instead of being resolved by input order. Missing or unsupported ownership remains absent; it is not replaced with a guessed value.

This projection is additive to canonical v1. It does not change the existing `player_areas` membership contract or player-building filtering. It preserves structural ownership evidence so a later raw diff can distinguish an observed owner-ID transition from an area merely entering the player-area projection. It does not assign gameplay meaning to owner IDs or to an ownership transition.

## Player-area fields

Each exported player area contains:

- `area_id` — required unsigned 32-bit integer;
- `owner_id` — required unsigned 32-bit integer. Current extraction exports areas selected as player-owned from the observed ownership structure; in tested saves that observed owner ID is `0`;
- `city_name_guid` — optional unsigned 32-bit integer when observed;
- `city_name_iterator` — optional unsigned 32-bit integer when observed.

The corresponding observed FileDB attributes are decoded only from their supported 4-byte little-endian representation; malformed widths fail closed before ownership or area identity is published.

Areas are sorted by `area_id`.

The canonical state intentionally does not include parser-derived area summaries such as building counts, kind counts, or GUID histograms. Consumers can recompute such summaries from `buildings`.

## Building/object fields

Each canonical building object contains:

- `area_id` — required unsigned 32-bit integer;
- `id` — required non-negative integer stable object ID as observed in the save. This field is intentionally not constrained to uint32; current synthetic coverage includes the supported 8-byte representation;
- `guid` — required unsigned 32-bit integer asset GUID decoded from the supported 4-byte representation; this is mutable object state, not part of stable identity;
- `components` — required array of unique component-tag strings sorted lexicographically;
- `position` — optional three-element array containing the decoded observed finite float32 transform values;
- `direction` — optional number containing the decoded observed finite float32 value;
- `rotation` — optional integer retained only when one supported legacy root rotation attribute is observed;
- `rotation_source` — optional string, exactly `Rotation` or `Rotation90`, identifying which observed legacy root attribute produced `rotation`.

If both `Rotation` and `Rotation90` are observed for the same object, parsing fails closed rather than choosing one by FileDB record order. Repeated observations of the same source retain the existing last-observation behavior; this contract does not assign gameplay semantics to either source name.

Buildings are sorted by `(area_id, id, guid)` within a session.

For the current raw structural diff, a session with an observed `session_guid` is identified by that GUID. If the GUID is absent, the diff falls back to the observed `session_id` together with `map`. A session lacking all usable identity fields, or duplicate sessions resolving to the same fallback identity, is rejected explicitly because comparing its objects safely would otherwise be ambiguous. Within the resolved session identity, the stable object comparison key is `(area_id, id)`.

A GUID change at a stable session/object identity is therefore state mutation rather than automatic remove/add lifecycle noise.

The parser does not assign axis names, map/grid units, orientation semantics, upgrade semantics, or human-readable GUID names in schema v1.

## Optionality and conservative absence

Optional fields are emitted only when the parser has decoded an observed supported representation. Missing or unsupported values are omitted rather than filled with plausible defaults. For float transform fields, IEEE-754 `NaN` and positive/negative infinity are treated as unsupported and omitted before canonical export; canonical v1 therefore exposes only finite `position` / `direction` numbers.

`session_guid` and `session_id` are exceptions: their keys are always present and use JSON `null` when the corresponding observed session descriptor value is absent. Keeping those identity slots explicit makes session comparison rules unambiguous, even though a state can remain canonical while lacking enough session identity for the separate raw-diff operation to compare it safely.

`observed_areas` is an additive optional field for compatibility with earlier schema-v1 documents. Newly parsed states emit it when the parser has the corresponding structural observation. A diff against a v1 state that lacks the field cannot invent ownership history from absence; ownership-transition evidence is emitted only where both compared states provide supported owner IDs for the same observed area identity.

## Determinism

For the same decoded game state and parser version, canonical semantic content and array ordering are deterministic:

- sessions use identity/descriptor ordering plus normalized canonical content as a final tie-breaker;
- observed areas use `area_id` ordering when present;
- player areas are sorted by `area_id`;
- buildings are sorted by `(area_id, id, guid)`;
- component sets are deduplicated and sorted.

This guarantee is about the JSON data model. It does **not** promise byte-identical `.gz` archives: gzip container metadata may vary between writes.

## Excluded parser/container representation

The following are intentionally not part of canonical v1:

- outer RDA member sizes or directory metadata;
- decompressed `data.a7s` size;
- embedded-session extraction index or binary blob size/path;
- total raw GameObject counters;
- recomputable area kind/building/GUID count summaries;
- temporary parser paths or traversal state.

These values may still be used internally for progress reporting or diagnostics without becoming downstream compatibility commitments.

## Compatibility policy

Consumers of schema v1 SHOULD ignore unknown object fields so that later roadmap work can add optional canonical data without forcing an immediate schema-version bump.

A new canonical schema version is required for an incompatible contract change such as:

- removing or renaming an existing v1 field;
- changing the type or required/optional status of an existing v1 field incompatibly;
- changing the stable-identity or ordering meaning promised by v1;
- changing the semantics of an existing field rather than adding new optional state.

Additive optional fields that preserve all existing v1 meanings may remain schema version `1`.

## Structural diffs

The current raw structural diff consumes canonical v1 states and emits object additions/removals, position changes, Direction changes, component changes, GUID changes, player-area projection additions/removals, and observed owner-ID transitions when both snapshots contain supported ownership for the same observed area. Its session fallback/rejection rules are described above. That diff format is a separate pre-semantic interface; this document does not declare a semantic-diff schema.

## `summary.json` is not a canonical state

A batch run also writes `summary.json`. Its state entries are deliberately compact projections and omit full building arrays. They therefore do **not** carry the canonical state's `schema` / `schema_version` markers.

Instead the batch report contains a top-level reference:

```json
{
  "canonical_schema": {
    "name": "anno-saves-parser/canonical-state",
    "version": 1
  },
  "states": [],
  "diffs": []
}
```

Consumers that need the canonical contract MUST read the corresponding `*.canonical.json.gz` files rather than treating batch projections as canonical states.
