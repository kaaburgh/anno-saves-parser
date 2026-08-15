# AGENTS.md

## Purpose

This repository reverse-engineers enough of the Anno 1800 save format to produce deterministic, compact canonical state and semantic diffs suitable for downstream analysis. Keep the parser useful on its own; AI coaching is a consumer, not a reason to put probabilistic logic into the parser.

## Source of truth

1. Working code and tests.
2. `ROADMAP.md` for planned scope and dependencies.
3. `docs/architecture.md` for durable architectural decisions and known format boundaries.
4. `README.md` for public CLI behavior.

If these disagree, fix the disagreement in the same PR.

## Scope discipline

- Keep each PR to one primary roadmap item or one narrowly-defined maintenance change.
- Do not mix format research, canonical-schema redesign, watcher UX, and AI/tutor behavior in one PR.
- Preserve existing CLI behavior unless the task explicitly changes it.
- A CLI option documented in README is a compatibility contract and needs regression tests.

## Validation

Before publishing a change, run:

```bash
python -m compileall -q anno_save_probe.py tests
python -m unittest discover -s tests -v
```

If a change touches real-save parsing, also run a local smoke test against at least two consecutive `.a7s` files when such proprietary fixtures are available. Never claim that smoke test ran if the files were unavailable.

## Proprietary data / fixtures

- Never commit `.a7s` saves, extracted proprietary game data, player profile data, or generated dumps derived from them.
- Keep regression tests synthetic wherever possible.
- When a bug can only be reproduced with a private save, reduce it to the smallest synthetic fixture or structural invariant before committing a test.
- `.gitignore` is a guardrail, not permission to handle user saves carelessly.

## Reverse-engineering discipline

- Separate observed facts from hypotheses in docs and code comments.
- Prefer deterministic parsing from observed structure over heuristic byte scanning when stable structure is known.
- Preserve unknown fields rather than assigning unsupported semantics.
- Stable IDs/GUIDs may be used as canonical identity; human-readable names should come from an explicit mapping/provenance layer, not guesses.
- Avoid copying large third-party implementation fragments. Record useful upstream/community references and independently implement only the behavior needed here.

## Runtime constraints

- The CLI intentionally has zero third-party runtime dependencies.
- Python 3.11+ is the supported baseline.
- Windows, including portable embeddable Python, is a first-class environment.
- Keep long-running CLI stages observable: print an immediate stage message and emit progress/heartbeat output at roughly one-second intervals while work continues.

## Durable changes

Update `ROADMAP.md`, `docs/architecture.md`, README, or tests when a change establishes a new durable fact or contract. Do not leave important format discoveries only in PR discussion.
