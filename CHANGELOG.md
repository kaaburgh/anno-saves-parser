# Changelog

## Unreleased

## 0.4.0 — 2026-08-15

- Add explicit `--workers N` save-level process parallelism with serial `--workers 1` as the conservative default.
- Bound in-flight save jobs to the resolved worker count while preserving chronological canonical-state, summary, and adjacent-diff ordering; reject canonical output-name collisions before scheduling using filesystem-independent Unicode-normalized case-folding so parallel completion order cannot silently overwrite snapshots.
- Keep parallel progress readable in the parent process and surface save-specific worker failures immediately, with cleanup heartbeats while already-running workers finish before clean executor/temp shutdown.
- Report CPU, available RAM, and temp-space context plus conservative warnings for aggressive explicit worker counts; reject the Windows `ProcessPoolExecutor` hard limit above 61 before pool construction.
- Add synthetic scheduling/order/failure/resource-policy regressions and record private-save scaling/resource measurements.

## 0.3.3 — 2026-08-15

- Emit deterministic `direction_changed` structural-diff events for stable building identities whose canonical `Direction` value changes.
- Preserve present↔absent Direction transitions explicitly as `null` on the missing side without assigning gameplay rotation semantics.
- Keep Direction changes orthogonal to GUID, movement, and component changes, preserve the map component of GUID-less fallback session identity, and expose their count in the CLI pair summary.
- Add synthetic coverage for direction-only mutations, coexistence, absence transitions, ordering, fallback session identity, unchanged values, and CLI reporting.

## 0.3.2 — 2026-08-15

- Reduce the dominant serial FileDB traversal cost by resolving relevant numeric tag/attribute IDs once per blob and scanning bounded session data with stdlib `mmap`.
- Stop copying embedded GameSession `BinaryData` into secondary temporary files; parse bounded offsets directly from the already-expanded `data.bin`.
- Keep mmap ranges aligned for Windows allocation granularity and preserve zero third-party runtime dependencies.
- Bound FileDB slice metadata/string reads and reject negative attribute sizes explicitly so corrupted slices cannot read into neighboring data.
- Add fully synthetic bounded-slice, standalone-equivalence and malformed-input regression coverage.
- Record representative local profiling methodology and before/after resource behavior in `docs/performance.md`.

## 0.3.1 — 2026-08-15

- Always report total elapsed time for the adjacent structural-diff phase in batch CLI output.
- Add opt-in `--timings` output with one elapsed-time line per adjacent save pair.
- Keep runtime timing metadata out of canonical state files and deterministic `summary.json` output.

## 0.3.0 — 2026-08-15

- Define canonical state schema v1 (`anno-saves-parser/canonical-state`, version `1`) as the stable downstream boundary for per-save `.canonical.json.gz` output.
- Normalize session, player-area, building and component ordering deterministically while preserving stable identity and conservative optional-field absence.
- Exclude container/parser diagnostics and recomputable area summaries from canonical state; keep compact `summary.json` projections explicitly distinct from full canonical documents.
- Make raw structural diffs consume canonical v1 states and reject the legacy pre-v1 prototype shape.
- Expose stable-object asset GUID mutations in structural diffs as deterministic `guid_changed` events with previous/current GUIDs and stable identity.
- Keep GUID changes semantic-neutral and orthogonal to additions/removals, movement, and component changes.
- Decode observed root-level player-building `Position` as a 12-byte little-endian float32 triple so canonical snapshots carry real transform data and existing `moved` diffs become observable.
- Preserve observed root-level `Direction` as a 4-byte float32 value when present, without assigning orientation semantics.
- Reject unsupported transform attribute sizes and non-finite float32 transform values conservatively before canonical export.
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
