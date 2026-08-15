# ROADMAP

The project is intentionally small. Items below are executable chunks rather than a promise to build a large framework.

## P0 — Parser baseline

### ASP-P0-1 — Dependency-free save parsing and batch CLI
**Status:** done  
**Depends on:** none

Parse current `.a7s` saves through RDA, zlib and FileDB v3; discover/sort autosaves by internal timestamp; support `--from`, `--limit`, `--list`, `-o`, `--version`; produce canonical snapshots and raw structural diffs; keep long stages observable.

### ASP-P0-2 — Repository baseline and CI
**Status:** done  
**Depends on:** ASP-P0-1

Commit the prototype, regression tests, agent guidance, architecture notes and cross-platform GitHub Actions.

## P1 — Canonical state

### ASP-P1-1 — Define canonical schema v1
**Status:** ready  
**Depends on:** ASP-P0-2

Make the canonical schema explicit and versioned. Preserve stable identity, session/area ownership and object/component data while excluding volatile parser-only representation.

### ASP-P1-2 — GUID/name provenance layer
**Status:** planned  
**Depends on:** ASP-P1-1

Resolve relevant GUIDs to human-readable names using a separately maintained, provenance-aware mapping without coupling core parsing to downloaded game assets.

### ASP-P1-3 — Economy state extraction
**Status:** planned  
**Depends on:** ASP-P1-1

Extract player population/workforce, money/balance, stocks/inventory and enough production statistics for deterministic economic analysis.

### ASP-P1-4 — Trade route extraction
**Status:** planned  
**Depends on:** ASP-P1-1

Canonicalize routes, stations, assigned ships, configured goods and useful visit/history state.

## P2 — Semantic diffs and timeline

### ASP-P2-1 — Object lifecycle semantic diff
**Status:** planned  
**Depends on:** ASP-P1-1, ASP-P1-2

Translate raw object additions/removals/moves/component changes into building/module lifecycle events while suppressing representation noise.

### ASP-P2-2 — Cluster modules into construction episodes
**Status:** planned  
**Depends on:** ASP-P2-1

Collapse field/module bursts and related infrastructure into higher-level construction episodes so one plantation complex is not hundreds of independent events.

### ASP-P2-3 — Economy deltas and decision episodes
**Status:** planned  
**Depends on:** ASP-P1-3, ASP-P2-1

Combine state deltas over consecutive autosaves into deterministic episodes suitable for downstream reasoning.

## P3 — Incremental collection

### ASP-P3-1 — Watch mode
**Status:** planned  
**Depends on:** ASP-P1-1

Watch a save directory, wait for a new `.a7s` write to stabilize, process it once, and append to an incremental timeline. Source saves remain read-only by default.

### ASP-P3-2 — Resume/cache semantics
**Status:** planned  
**Depends on:** ASP-P3-1

Skip already processed saves safely using internal metadata/content identity and make interrupted sessions resumable.

## P4 — Tutor handoff

### ASP-P4-1 — Stable timeline export contract
**Status:** planned  
**Depends on:** ASP-P2-3

Define a compact deterministic JSON contract that a separate AI tutor can consume. The parser repository does not own prompting, coaching policy, or LLM integration.
