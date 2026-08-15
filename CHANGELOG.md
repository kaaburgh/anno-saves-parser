# Changelog

## Unreleased

- Expose stable-object asset GUID mutations in structural diffs as deterministic `guid_changed` events with previous/current GUIDs and stable identity.
- Keep GUID changes semantic-neutral and orthogonal to additions/removals, movement, and component changes.
- Add synthetic regression coverage for GUID-only mutations, deterministic ordering, unchanged GUIDs, and coexisting component changes.

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
