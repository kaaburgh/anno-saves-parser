# Top-level FileDB mmap investigation (#35)

This note preserves the already-observed benchmark evidence behind issue #35. It does not mark the optimization implemented and does not change parser behavior.

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

## Remaining acceptance boundary

Issue #35 remains open. Before it can be considered complete, the production scanner still needs:

- the actual read-only mmap/offset implementation with Windows allocation/portability preserved;
- all existing bounds, negative-size, malformed, and truncated-input rejection behavior preserved;
- a committed differential oracle comparing the optimized scanner with the current buffered reference on synthetic/reduced fixtures;
- exact deterministic session-descriptor equivalence;
- validation on at least two consecutive private saves when available;
- representative before/after timing recorded after the production change.

PyPy remains informative benchmark evidence only; it is not promoted to a required CI runtime by this investigation.
