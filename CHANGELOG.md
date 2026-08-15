# Changelog

## 0.2.1 — 2026-08-15

- Render per-save parse progress in place on interactive terminals: one persistent completion line per save plus one live detail line for the current save.
- Keep redirected, piped, and CI output line-oriented and free of ANSI cursor-control sequences.
- Truncate live terminal lines to avoid wrapping that would break cursor accounting.
- Add synthetic regression tests for interactive rendering, non-TTY logging, and terminal-width handling.

## 0.2.0 — 2026-08-15

- Restore and regression-test `--from`, `--limit`, `--list`, `-o/--output` and `--version`.
- Add immediate progress output and approximately one-second heartbeats during long-running parsing stages.
- Prefer internal save `LastModTime` for discovery ordering and date-based selection.
- Keep the parser dependency-free and compatible with portable Windows Python.

## 0.1.0 — 2026-08-15

- Initial feasibility parser for RDA → zlib → FileDB v3 state extraction.
- Produce compact canonical building snapshots and consecutive structural diffs.
