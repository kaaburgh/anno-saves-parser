# Architecture

## Goal

Turn a sequence of Anno 1800 `.a7s` saves into compact deterministic state and, eventually, a semantic timeline. The parser should answer **what changed** without requiring an LLM and without shipping proprietary save data.

## Current pipeline

```text
.a7s container
  -> RDA v2.2 directory
  -> embedded meta/header/gamesetup/data members
  -> zlib-decompressed FileDB state
  -> FileDB/BBDom v3 traversal
  -> GameSessions / embedded session BinaryData
  -> parser-internal session/object extraction
  -> canonical state schema v1
  -> canonical JSON.gz
  -> consecutive structural diff
```

The implementation is currently a single dependency-free module, `anno_save_probe.py`. That is deliberate while format knowledge is still changing quickly; split it into packages only when boundaries become stable enough to reduce complexity rather than merely move functions between files.

### Bounded FileDB session traversal

The expanded top-level `data.bin` is the single temporary FileDB backing store for a save. `extract_sessions()` records each embedded GameSession `BinaryData` value as a bounded `(offset, length)` view into that file instead of copying the blob into a second temporary file. `parse_session()` reads the FileDB trailer/dictionaries relative to that bounded slice and maps only the session range with stdlib `mmap`, aligned to `mmap.ALLOCATIONGRANULARITY` so the same path works on Windows.

Relevant tag and attribute numeric IDs are resolved once from each FileDB dictionary. The hot traversal then compares numeric IDs and materializes bytes only for attributes used by the parser's current canonical subset. Slice metadata and attribute lengths are bounds-checked; malformed dictionaries or negative attribute sizes fail explicitly rather than reading neighboring bytes from the parent file.

This is a parser-internal performance representation only. It does not change canonical schema v1 or structural-diff semantics. Benchmark methodology and resource measurements are recorded in [performance.md](performance.md).

## Observed invariants used today

- Modern saves observed during feasibility testing use an RDA `Resource File V2.2` outer container.
- The outer archive exposes `meta.a7s`, `header.a7s`, `gamesetup.a7s`, and `data.a7s` members in the tested saves.
- `meta.a7s` contains `LastModTime`, which is preferred over filesystem mtime for chronological ordering.
- The main state is compressed and expands dramatically relative to the outer save size; parsing should therefore avoid retaining redundant decoded copies longer than necessary.
- `GameSessions` contains session-specific binary state.
- Player-owned areas can be separated from AI-owned areas using ownership data observed in the save structure.
- Many world objects expose stable object IDs plus GUIDs, which are useful canonical identity candidates.
- Tested player-building objects expose transform attributes directly at the root object depth: `Position` is a 12-byte little-endian float32 triple and `Direction`, when present, is a 4-byte little-endian float32 value.

These are observations from tested saves, not a guarantee that every game version or corrupted/modded save follows the same structure. Parser failures should be explicit rather than silently producing plausible-looking partial state.

## Canonical-state principles

1. **Deterministic.** The same decoded state and parser version should produce the same canonical data model and ordering.
2. **Small.** Do not retain raw decoded FileDB trees in the output.
3. **Identity-preserving.** Keep enough stable IDs to compare consecutive saves.
4. **Semantic restraint.** Unknown fields stay unknown; naming and interpretation require evidence.
5. **Versioned.** Downstream consumers depend on an explicit schema identifier/version rather than parser-internal dictionaries.
6. **Player-focused by default.** The tutor use case primarily needs the player's economy, but raw format support should not irreversibly discard context needed to validate ownership/filtering.

## Canonical v1 export boundary

`build_canonical_state()` is the boundary between parser-internal representation and downstream state. The per-save `*.canonical.json.gz` documents use:

- schema name `anno-saves-parser/canonical-state`;
- schema version `1`;
- deterministic session, area, building and component ordering;
- explicit session identity slots;
- player-area ownership/name metadata;
- stable object identity, asset GUID/components and conservatively decoded transform state.

The normative contract is [canonical-schema-v1.md](canonical-schema-v1.md). That document owns field meanings, ordering, optionality, excluded representation and compatibility policy.

Parser/container diagnostics are deliberately outside this boundary. RDA sizes, decompressed size, embedded-session extraction index/blob size/path, total raw GameObject counters and recomputable area summary counts may be useful while parsing but are not compatibility commitments.

The batch `summary.json` is also outside the canonical-state schema. Its `states` entries are compact projections without building arrays and therefore do not carry canonical `schema` / `schema_version` markers. A top-level `canonical_schema` reference records which canonical contract produced those projections.

Canonical determinism refers to the JSON data model and ordering, not byte-for-byte reproducibility of gzip containers; gzip metadata may differ between writes.

## Structural diff identity and GUID mutations

The raw structural diff consumes canonical v1 states. For session identity it prefers an observed `session_guid`. When `session_guid` is absent, it uses the observed `session_id` together with `map` as a conservative fallback. A session with none of those usable identifiers, or duplicate sessions that resolve to the same fallback identity, is rejected explicitly rather than allowing object dictionaries to overwrite one another silently.

Within an identified session, a player-building object's stable comparison key is `(area_id, object id)`. An asset `guid` is object state, not part of that stable object key: observed real-save sequences contain objects that retain the same stable identity while their GUID changes.

Such transitions are emitted as raw `guid_changed` events with `from_guid` and `to_guid` plus the stable identity and current component set. They are deliberately not classified as upgrades, construction stages, or any other gameplay lifecycle event until the later provenance/semantic layers have evidence for that interpretation.

A single stable object may emit a GUID mutation together with another independent structural event such as a component or movement change. Event lists derived from common stable keys are ordered deterministically by the normalized session identity plus area/object IDs.

The structural-diff output is not declared as the canonical-state schema and does not yet have a semantic-diff contract of its own.

## Observed object transform encoding

Direct inspection of private FileDB/BBDom v3 session data established the transform boundary used by `parse_session()`:

```text
.../AreaManager_N/AreaObjectManager/GameObject/objects/#1
  ID
  guid
  Position   # 12 bytes, <fff>
  Direction  # 4 bytes, <f>, optional
  ...components...
```

`Position` is decoded only for the observed 12-byte representation and stored as the three float32 values promoted to Python floats. Unsupported sizes remain absent rather than being reinterpreted heuristically. `Direction` is likewise decoded only from the observed 4-byte float32 representation. The parser does not label the axes, infer map/grid units, or assign orientation semantics beyond preserving the decoded raw values.

Across multiple consecutive private-save pairs, `Position` was present on every canonical player-building object inspected across all observed sessions. At least one stable object identity also changed `Position` between consecutive saves while remaining the same object, validating that the existing raw `moved` event can represent an observed transform change without manufacturing add/remove lifecycle noise.

`Direction` remains semantic-neutral raw object state. Structural diffs emit a deterministic `direction_changed` event when the value changes for a stable object identity, including present↔absent transitions as explicit `null` on the missing side. Events carry the session map when it is present so GUID-less `(session_id, map)` fallback identities remain attributable. Direction changes stay orthogonal to GUID, movement, and component events; the parser does not label them as gameplay rotation.

## Why five-minute autosaves are promising

Initial consecutive-save experiments produced sparse, interpretable object changes in ordinary intervals and one large but coherent module-heavy construction burst. That suggests semantic clustering can recover useful decision episodes without logging every click. This is a feasibility result, not yet a quality guarantee; future economy extraction will determine how much intent can be inferred from state alone.

## Batch concurrency boundary

Save canonicalization is independent until adjacent diffs are built. The CLI therefore permits explicit bounded process-level concurrency with `--workers N`; the default remains one worker. Parallel workers receive only one save path at a time, build their own temporary `data.bin`, return canonical state to the parent, and do not emit interleaved stage logs. The parent preserves chronological state/diff ordering and owns output serialization/progress. This is a runtime scheduling concern only and does not change canonical schema or structural-diff semantics.

## CLI observability contract

Long operations must not look hung:

- print the start of a new stage immediately and flush stdout;
- if a stage completes quickly, print its result directly;
- if it continues, emit a heartbeat/progress line roughly once per second;
- include useful counters/percentages where cheaply available.

This behavior is part of the CLI UX and is covered by regression tests.

## Boundaries / non-goals

- No LLM calls in the parser.
- No destructive save cleanup by default.
- No committed proprietary `.a7s` fixtures.
- No requirement for RDAExplorer/FileDBReader executables at runtime.
- No dependency on game assets for the core parser.
- No human-readable GUID naming in the canonical core without an explicit provenance layer.

A future watcher and an AI tutor should consume stable parser outputs rather than reach into parser internals.
