# Changelog

## 0.2.0 — 2026-08-15

- Restore and regression-test `--from`, `--limit`, `--list`, `-o/--output` and `--version`.
- Add immediate progress output and approximately one-second heartbeats during long-running parsing stages.
- Prefer internal save `LastModTime` for discovery ordering and date-based selection.
- Keep the parser dependency-free and compatible with portable Windows Python.

## 0.1.0 — 2026-08-15

- Initial feasibility parser for RDA → zlib → FileDB v3 state extraction.
- Produce compact canonical building snapshots and consecutive structural diffs.
