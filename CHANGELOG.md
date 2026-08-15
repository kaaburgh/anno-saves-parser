# Changelog

## Unreleased

## 0.3.0 — 2026-08-15

- Define canonical state schema v1 (`anno-saves-parser/canonical-state`, version `1`) as the stable downstream boundary for per-save `.canonical.json.gz` output.
- Normalize session, player-area, building and component ordering deterministically while preserving stable identity and conservative optional-field absence.
- Exclude container/parser diagnostics and recomputable area summaries from canonical state; keep compact `summary.json` projections explicitly distinct from full canonical documents.
- Make raw structural diffs consume canonical v1 states and reject the legacy pre-v1 prototype shape.
- Expose stable-object asset GUID mutations in structural diffs as deterministic `guid_changed` events with previous/current GUIDs and stable identity.
- Keep GUID changes semantic-neutral and orthogonal to additions/removals, movement, and component changes.
- Decode observed root-level player-building `Position` as a 12-byte little-endian float32 triple so canonical snapshots carry real transform data and existing `moved` diffs become observable.
- Preserve observed root-level `Direction` as a 4-byte float32 value when present, without assigning orientation semantics.
- Reject unsupported transform attribute sizes conservatively.
- Add synthetic regression coverage for canonical v1 shape/determinism, batch-summary boundaries, GUID mutations, movement and transform decoding.

## 0.2.1 — 2026-08-15

- Render per-save parse progress in place on interactive terminals: one persistent completion line per save plus one live detail line for the current save.
- Enable and verify Windows Virtual Terminal processing before using cursor-control sequences; otherwise fall back to line-oriented logging.
- Keep redirected, piped, and CI output line-oriented and free of ANSI cursor-control sequences.
- Truncate live terminal lines by rendered terminal-cell width to avoid wrapping that would break cursor accounting.
- Close an active live parse block cleanly before propagating parse/write failures.
- Add synthetic regression tests for interactive rendering, Windows VT fallback, failure cleanup, non-TTY logging, and terminal-width handling.

## 0.2.0 — 2026-08-15

- Restore and regression-test `--from`, `--limit`, `--list`, `-o/--output` and `--version`.
- Add immediate progress output and approximately one-second heartbeats during long-running parsing stages.
- Prefer internal save `LastModTime` for discovery ordering and date-based selection.
- Keep the parser dependency-free and compatible with portable Windows Python.

## 0.1.0 — 2026-08-15

- Initial feasibility parser for RDA → zlib → FileDB v3 state extraction.
- Produce compact canonical building snapshots and consecutive structural diffs.
