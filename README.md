# anno-saves-parser

Dependency-free Python tooling for extracting a compact, stable view of **Anno 1800** save games and comparing consecutive autosaves.

The project started as a feasibility probe for a personal AI tutor: instead of feeding an LLM raw `.a7s` files, the parser turns them into small canonical snapshots that can later support semantic diffs, timelines, decision episodes, and coaching.

## Status

**Early prototype / format research.** The current CLI can:

- discover `.a7s` files in one or more paths;
- sort them using the save's internal `LastModTime` rather than filesystem timestamps;
- start from a save name such as `Autosave 711` or a date such as `2026-08-15`;
- limit a batch with `--limit`;
- parse RDA → zlib → FileDB v3 without external executables or Python packages;
- extract session/player-area building objects into compressed canonical JSON;
- compare consecutive canonical snapshots;
- emit immediate progress plus ~1-second heartbeats during long operations;
- keep per-save parse progress compact in interactive terminals with one live status line, while preserving ordinary line-oriented logs for redirects, pipes, and CI.

The canonical model is intentionally incomplete. Population, workforce, inventory, production/demand, trade routes, GUID naming, and semantic episode reconstruction belong to follow-up work.

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

Check the exact CLI version:

```powershell
python .\anno_save_probe.py --version
```

## Output

For each processed save the CLI writes a compressed canonical snapshot, plus a `summary.json` for the batch:

```text
output/
  Autosave_711.canonical.json.gz
  Autosave_712.canonical.json.gz
  Autosave_713.canonical.json.gz
  summary.json
```

The parser is read-only with respect to the source save directory.

When stdout is attached to an interactive terminal, each completed save leaves one permanent `[parse N/M] done ...` line. The currently parsed save uses one header plus one in-place live detail line. When stdout is redirected or captured, progress remains normal newline-delimited text with no cursor-control sequences.

## Development

Run the same checks as CI:

```bash
python -m compileall -q anno_save_probe.py tests
python -m unittest discover -s tests -v
```

No real Anno save files are committed to this repository. Unit tests use synthetic data/mocks; local `.a7s` files are ignored by Git.

See [ROADMAP.md](ROADMAP.md) for planned work and [docs/architecture.md](docs/architecture.md) for the current data pipeline and boundaries.
