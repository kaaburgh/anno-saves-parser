# Top-level FileDB mmap investigation (#35)

This note preserves the already-observed benchmark evidence behind issue #35 and the bounded implementation scaffolding now committed for it. The production `extract_sessions()` path is still unchanged.

## Scope

The current `extract_sessions()` top-level FileDB traversal still visits roughly 2.7 million records through repeated buffered `read(8)` / `seek()` operations before the embedded GameSession blobs are parsed. A local prototype replaced only that traversal with read-only `mmap` plus offset-based `struct.unpack_from`, preserving the same stack/context logic and descriptor schema.

The measurements below used the parsing core at `main@b768091e928eda4924066bca609ff2bc926fdf77` and representative private `Autosave 686` (`data.bin` about 266 MiB) on local Linux x86-64. The save and derived state remain private. These numbers are local evidence, not a cross-machine or Windows performance contract.

## Representative results

| Runtime | Current `extract_sessions()` | mmap prototype | Observed speedup |
| --- | ---: | ---: | ---: |
| CPython 3.13.5 | ~0.83–0.89 s | ~0.52–0.58 s | ~1.5–1.7x |
| PyPy 7.3.19 / Python 3.11.11 | ~0.16–0.17 s | ~0.036–0.049 s | ~3.3–4.7x |

The prototype returned an exactly equal ordered list of session descriptors, including `binary_offset`, `binary_size`, GUID/ID/map metadata, and ordering.

The evidence supports a bounded pure-Python implementation candidate: move top-level session discovery to the same read-only mmap/offset traversal style already used for bounded GameSession blobs. It does not justify native code, canonical-schema changes, decompression changes, worker-policy changes, or public CLI changes.

## Committed scanner seams

`top_level_session_scan.py` contains the read-only mmap/offset traversal as the production candidate. It intentionally receives the already-decoded FileDB metadata (`tags_off`, tag dictionary, and attribute dictionary) rather than implementing a second metadata parser.

The module also retains the historical buffered traversal as `scan_top_level_sessions_buffered_reference()`. That function is evidence/test-only: it exists so differential and private-target validation remain independent after production `extract_sessions()` eventually switches to mmap. It is not a second public parser mode.

The synthetic differential oracle compares three paths on the same reduced FileDB inputs:

- the retained buffered reference scanner;
- current production `extract_sessions()`;
- the mmap scanner.

The oracle requires exact descriptor equality on the two-session fixture and matching fail-closed errors for negative attribute sizes and truncated payloads. The operator target harness compares the retained buffered reference directly with the mmap scanner, rather than treating production `extract_sessions()` as its reference; this preserves the evidence oracle across the future production switch.

## Remaining acceptance boundary

Issue #35 remains open. Before it can be considered complete, the production scanner still needs:

- wiring `extract_sessions()` to the committed read-only mmap/offset helper while preserving Windows portability and progress behavior;
- all existing bounds, negative-size, malformed, and truncated-input rejection behavior preserved;
- exact deterministic session-descriptor equivalence;
- validation on at least two consecutive private saves when available;
- representative before/after timing recorded after the production change.

The committed differential oracle, retained buffered reference, mmap helper, and target harness are preparatory repository evidence, not proof that the production scanner has changed. PyPy remains informative benchmark evidence only; it is not promoted to a required CI runtime by this investigation.
