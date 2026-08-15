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
  -> player-owned areas
  -> stable building/object identities
  -> canonical JSON.gz
  -> consecutive structural diff
```

The implementation is currently a single dependency-free module, `anno_save_probe.py`. That is deliberate while format knowledge is still changing quickly; split it into packages only when boundaries become stable enough to reduce complexity rather than merely move functions between files.

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

1. **Deterministic.** The same save and parser version should produce the same canonical state.
2. **Small.** Do not retain raw decoded FileDB trees in the output.
3. **Identity-preserving.** Keep enough stable IDs to compare consecutive saves.
4. **Semantic restraint.** Unknown fields stay unknown; naming and interpretation require evidence.
5. **Versioned.** Before downstream consumers depend on it, introduce an explicit canonical schema version.
6. **Player-focused by default.** The tutor use case primarily needs the player's economy, but raw format support should not irreversibly discard context needed to validate ownership/filtering.

## Structural diff identity and GUID mutations

The pre-schema-v1 structural diff treats `(session_guid, area_id, object id)` as the stable comparison key for player-building objects. An asset `guid` is object state, not part of that stable key: observed real-save sequences contain objects that retain the same stable identity while their GUID changes.

Such transitions are emitted as raw `guid_changed` events with `from_guid` and `to_guid` plus the stable identity and current component set. They are deliberately not classified as upgrades, construction stages, or any other gameplay lifecycle event until the later provenance/semantic layers have evidence for that interpretation.

A single stable object may emit a GUID mutation together with another independent structural event such as a component or movement change. Event lists derived from common stable keys are ordered deterministically by the stable object key.

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

`Direction` is canonical object state but is not yet a dedicated structural-diff event. A later schema/semantic task may decide whether orientation changes need their own event type.

## Why five-minute autosaves are promising

Initial consecutive-save experiments produced sparse, interpretable object changes in ordinary intervals and one large but coherent module-heavy construction burst. That suggests semantic clustering can recover useful decision episodes without logging every click. This is a feasibility result, not yet a quality guarantee; future economy extraction will determine how much intent can be inferred from state alone.

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

A future watcher and an AI tutor should consume stable parser outputs rather than reach into parser internals.
