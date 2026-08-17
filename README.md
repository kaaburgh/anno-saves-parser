# anno-saves-parser

Dependency-free Python tooling for extracting a compact, stable view of **Anno 1800** save games and comparing consecutive autosaves.

The project started as a feasibility probe for a personal AI tutor: instead of feeding an LLM raw `.a7s` files, the parser turns them into small canonical snapshots that can later support semantic diffs, timelines, decision episodes, and coaching.

## Status

**Early format research with canonical state schema v1.** The current CLI can:

- discover `.a7s` files in one or more paths;
- sort them using the save's internal `LastModTime` rather than filesystem timestamps;
- start from a save name such as `Autosave 711` or a date such as `2026-08-15`;
- limit a batch with `--limit`;
- opt into bounded save-level process parallelism with `--workers N` while keeping serial execution as the default;
- optionally enrich structural diffs with exact GUID names from an operator-owned provenance-aware mapping via `--guid-mapping PATH`, without changing canonical snapshots or numeric GUID identity;
- parse RDA → zlib → FileDB v3 without external executables or Python packages;
- extract session/player-area building objects into compressed canonical JSON using explicit schema v1;
- preserve stable object identity, GUID/components, and observed transform state while excluding parser/container diagnostics from the canonical contract;
- compare consecutive canonical v1 snapshots, including independent raw GUID, movement, component, and `Direction` mutations for stable objects;
- always report total structural-diff elapsed time, with optional `--timings` output for each adjacent save pair;
- emit immediate progress plus ~1-second heartbeats during long operations;
- keep per-save parse progress compact in interactive terminals with one live status line, while preserving ordinary line-oriented logs for redirects, pipes, CI, and terminals without usable cursor-control support.

Canonical schema v1 is documented in [docs/canonical-schema-v1.md](docs/canonical-schema-v1.md). It is intentionally incomplete in breadth: population, workforce, inventory, production/demand, trade routes, real GUID mapping source selection, and semantic episode reconstruction belong to follow-up work and may be added as compatible optional state where possible.

## Requirements

Python **3.11+**. Runtime dependencies: **none outside the standard library**.

A portable Windows embeddable Python distribution also works:

```powershell
.\python\python.exe .\anno_save_probe.py --version
```

## Usage

List discovered saves:

```powershell
python .\anno_save_probe.py "C:\Users\gamer\Documents\Anno 1800\accounts\<account>\<profile>" --list
```

Start from a save name:

```powershell
python .\anno_save_probe.py "C:\...\<profile>" --from "Autosave 711" -o output\
```

Start from the first save on or after a date:

```powershell
python .\anno_save_probe.py "C:\...\<profile>" --from 2026-08-15 -o output\
```

Process only the first three selected saves:

```powershell
python .\anno_save_probe.py "C:\...\<profile>" --from "Autosave 711" --limit 3 -o 711_l3\
```

Use two parser processes for a larger batch:

```powershell
python .\anno_save_probe.py "C:\...\<profile>" --from "Autosave 664" --workers 2 -o parallel_probe\
```

`--workers 1` is the default and preserves the detailed serial progress view. Values above `1` use bounded process workers so the CPU-heavy FileDB traversal is not limited by the GIL. The parent keeps at most the resolved worker count active, preserves chronological state/diff ordering even when saves finish out of order, and reports aggregate progress instead of interleaving worker logs. Each active disk-backed worker may need roughly 300–400 MiB of RAM plus about 320 MiB of temporary storage; the CLI reports available resources and warns about obviously aggressive explicit settings without silently overriding them. On Windows, a resolved active count above the standard-library `ProcessPoolExecutor` hard limit of 61 is rejected before pool construction with a clear CLI error. If one worker fails, the failure is surfaced immediately; pending work is cancelled and roughly one-second cleanup heartbeats remain visible while already-running workers finish and remove their temporary directories.

Optionally enrich only the structural diffs written to `summary.json` with exact names from an operator-owned GUID mapping:

```powershell
python .\anno_save_probe.py "C:\...\<profile>" --guid-mapping "C:\...\guid-mapping.json" -o mapped_probe\
```

The mapping must satisfy the provenance contract in [docs/guid-mapping.md](docs/guid-mapping.md). It is validated before save discovery and parsing; unreadable, malformed, or incompatible input fails closed. Omitting `--guid-mapping` preserves the existing output shape. Supplying it leaves compressed canonical snapshots and every numeric GUID unchanged while adding mapping provenance and parallel nullable name fields to summary diffs. The parser does not download or select a real Anno mapping source.

Show per-adjacent-pair structural diff timings as well as the always-on total diff time:

```powershell
python .\anno_save_probe.py "C:\...\<profile>" --from "Autosave 711" --limit 10 --timings -o timing_probe\
```

Check the exact CLI version:

```powershell
python .\anno_save_probe.py --version
```

## Output

For each processed save the CLI writes a compressed **canonical state v1** document, plus a compact `summary.json` batch report. Before parsing starts, the selected batch is rejected if two source saves would map to the same canonical filename (for example because spaces normalize to underscores, two input directories contain the same basename, or names differ only by case/Unicode normalization), preventing silent overwrite and completion-order-dependent output. Collision comparison deliberately uses Unicode NFC + case-folding rather than host `normcase`, so safety does not depend on whether a POSIX-mounted output volume is case-sensitive:

```text
output/
  Autosave_711.canonical.json.gz
  Autosave_712.canonical.json.gz
  Autosave_713.canonical.json.gz
  summary.json
```

Each `*.canonical.json.gz` contains the normative schema markers:

```json
{
  "schema": "anno-saves-parser/canonical-state",
  "schema_version": 1,
  "source": {"save_name": "..."},
  "sessions": []
}
```

`summary.json` is **not** another canonical state file. It contains compact per-save projections and diffs plus a top-level `canonical_schema` reference; full building arrays remain only in the corresponding compressed canonical files. See [the v1 schema contract](docs/canonical-schema-v1.md) for field, ordering, optionality, and compatibility rules.

Structural-diff timing is CLI execution metadata only. Every batch reports the phase start and total elapsed time, for example:

```text
[diff] comparing 9 adjacent save pair(s)
[diff] done in 0.8s: 9 pair(s)
```

With `--timings`, the CLI additionally prints one elapsed-time line per adjacent pair. Timing values are deliberately **not** stored in `summary.json` or canonical state files, so deterministic analysis artifacts are unchanged by machine speed or runtime conditions.

The parser is read-only with respect to the source save directory.

When stdout is attached to an interactive terminal with usable cursor-control support, each completed save leaves one permanent `[parse N/M] done ...` line. The currently parsed save uses one header plus one in-place live detail line. On Windows the CLI enables and verifies Virtual Terminal processing before using cursor-control sequences; if that is unavailable, or when stdout is redirected/captured, progress falls back to normal newline-delimited text. Live lines are fitted by terminal display width, and a failed parse closes the live block before the exception is propagated.

## Development

Run the same checks as CI:

```bash
python -m compileall -q anno_save_probe.py tests
python -m unittest discover -s tests -v
```

No real Anno save files are committed to this repository. Unit tests use synthetic data/mocks; local `.a7s` files are ignored by Git.

See [ROADMAP.md](ROADMAP.md) for planned work, [docs/architecture.md](docs/architecture.md) for the current data pipeline and boundaries, [docs/performance.md](docs/performance.md) for parser profiling methodology and optimization results, and [docs/canonical-schema-v1.md](docs/canonical-schema-v1.md) for the normative canonical state contract.
