# Top-level FileDB mmap investigation (#35)

This note preserves the already-observed benchmark evidence behind issue #35 and the bounded implementation/evidence scaffolding committed for it. Production `extract_sessions()` is now wired to the read-only mmap scanner on the active PR for #35; the retained buffered scanner remains evidence/test-only.

## Scope

Historically, `extract_sessions()` visited roughly 2.7 million top-level FileDB records through repeated buffered `read(8)` / `seek()` operations before the embedded GameSession blobs were parsed. A local prototype replaced only that traversal with read-only `mmap` plus offset-based `struct.unpack_from`, preserving the same stack/context logic and descriptor schema.

The measurements below used the parsing core at `main@b768091e928eda4924066bca609ff2bc926fdf77` and representative private `Autosave 686` (`data.bin` about 266 MiB) on local Linux x86-64. The save and derived state remain private. These numbers are historical/local evidence, not post-integration target validation and not a cross-machine or Windows performance contract.

## Representative results

| Runtime | Buffered reference | mmap prototype | Observed speedup |
| --- | ---: | ---: | ---: |
| CPython 3.13.5 | ~0.83–0.89 s | ~0.52–0.58 s | ~1.5–1.7x |
| PyPy 7.3.19 / Python 3.11.11 | ~0.16–0.17 s | ~0.036–0.049 s | ~3.3–4.7x |

The prototype returned an exactly equal ordered list of session descriptors, including `binary_offset`, `binary_size`, GUID/ID/map metadata, and ordering.

The evidence supports a bounded pure-Python implementation: top-level session discovery uses the same read-only mmap/offset traversal style already used for bounded GameSession blobs. It does not justify native code, canonical-schema changes, decompression changes, worker-policy changes, or public CLI changes.

## Scanner seams and independent oracle

`top_level_session_scan.py` contains `scan_top_level_sessions_mmap()`, which receives already-decoded FileDB metadata (`tags_off`, tag dictionary, and attribute dictionary) rather than implementing a second metadata parser.

The module also retains the historical buffered traversal as `scan_top_level_sessions_buffered_reference()`. That function is evidence/test-only: it keeps differential and private-target validation independent after production becomes mmap-backed. It is not a second public parser mode.

The synthetic differential oracle compares the retained buffered reference and mmap scanner on the same reduced FileDB inputs and requires exact descriptor equality plus matching fail-closed errors for negative attribute sizes and truncated payloads. A focused production-path regression additionally verifies that `anno_save_probe.extract_sessions()` delegates the top-level traversal to `scan_top_level_sessions_mmap()` while preserving the existing `bb_meta()` metadata path and progress object.

The operator target harness compares the retained buffered reference directly with the mmap scanner, rather than treating production `extract_sessions()` as its reference. Its distinct-path/distinct-content checks and verified snapshots preserve an independent two-save target oracle after the production switch.

## Remaining acceptance boundary

Issue #35 remains open. The cloud-side production integration and synthetic regression do not substitute for proprietary-target evidence. Before the issue can be considered complete, the production-integrated head still needs:

- validation on at least two distinct consecutive representative private saves through the retained-buffered-vs-mmap target harness;
- representative post-integration timing recorded for the production head, with CPython as the required default-runtime evidence and PyPy informative where available;
- conservative Windows post-integration evidence before treating the performance figures as portable.

The retained buffered reference, mmap implementation, synthetic differential coverage, and target harness establish implementation capability and an independent validation procedure. They do not establish the remaining real-save claims until the operator-owned target run is performed.
