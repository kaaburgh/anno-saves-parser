## Project-specific parser contract

- Source `.a7s` saves are read-only. Never modify or delete source saves as part of parsing or analysis.
- Never commit proprietary `.a7s` saves, player/profile data, extracted proprietary game data, or generated private dumps. Real-save validation may use a private local corpus; committed regression fixtures should be synthetic or reduced structural invariants.
- Keep observed format facts separate from hypotheses and unsupported gameplay semantics. Prefer deterministic structural parsing over heuristic byte scanning where stable structure is known, and preserve unknown or absent values instead of inventing plausible values.
- Stable IDs and GUIDs may be canonical identity. Human-readable GUID/name resolution requires an explicit provenance-aware mapping layer rather than guesses.
- Parser, canonical-state, diff, and future economic calculations remain deterministic. Probabilistic coaching or LLM reasoning must not leak into factual parser outputs.
- The parser keeps zero third-party runtime dependencies unless a later roadmap item explicitly changes that contract.
- Python 3.11+ and Windows, including portable embeddable Python, are first-class environments. Avoid POSIX-only path, encoding, process, or line-ending assumptions.
- Long-running CLI stages remain observable with immediate stage output and roughly one-second progress or heartbeat output while work continues.
- README-documented CLI behavior is a compatibility contract and requires regression coverage when changed.
- Important format, architecture, compatibility, or evidence discoveries belong in durable repository docs, not only PR discussion.

## Repository validation

Before publishing a change, run:

```bash
python -m compileall -q anno_save_probe.py tests
python -m unittest discover -s tests -v
```

If a change touches real-save parsing, also run a smoke test against at least two consecutive private `.a7s` files when such fixtures are available. Never claim that smoke test ran when the files were unavailable.

The existing cross-platform CI matrix is part of the validation contract. Process/policy changes must preserve the parser checks while adding their own deterministic validation rather than weakening or replacing existing tests.
