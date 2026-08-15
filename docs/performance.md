# Parser performance

This document records durable profiling conclusions and methodology. Numbers are local measurements, not a cross-machine benchmark or performance contract. Real Anno save files remain private and are never committed as fixtures.

## Method

Issue #11 was investigated with consecutive private saves representative of the current corpus. Measurements were repeated locally with Python's monotonic/performance counters, `cProfile`, and `/usr/bin/time -v`. Synthetic FileDB fixtures in the repository cover semantics and corruption boundaries; private saves are used only for local smoke/profiling.

The stages measured independently were:

1. RDA directory/member read;
2. zlib decompression and write of the expanded top-level `data.bin`;
3. top-level GameSession location;
4. session FileDB traversal;
5. canonical-state normalization/sorting;
6. gzip JSON serialization;
7. adjacent structural diff.

OS page cache and temporary-storage state materially affect short runs, so ranges are more meaningful than single timings.

## Baseline finding

`parse_session()` was the dominant serial CPU stage. Profiling showed millions of small buffered reads, `struct.unpack` calls, dictionary name lookups and stack/context operations per save. A naive whole-file `mmap` prototype was rejected: by itself it changed traversal time only marginally in the measured environment and could increase file-backed resident memory substantially.

The secondary GameSession copy was also avoidable I/O: after expanding the top-level FileDB, the old pipeline copied each embedded session blob into another temporary file and then reopened those files for parsing.

## Chosen optimization

The production path combines two measured improvements:

- keep each embedded session as a bounded `(offset, length)` slice of `data.bin`, eliminating secondary session-file copies;
- resolve relevant FileDB numeric IDs once, then use bounded mmap traversal while materializing only attributes required by the current canonical subset.

The mapping is allocation-granularity aligned for Windows and uses only the Python standard library. Bounds are validated against the declared session slice before dictionary or attribute data is consumed.

## Representative results

On repeated representative local runs, the pre-optimization pipeline through session parsing was roughly **9.7–10.2 s/save**. The bounded numeric-ID traversal was roughly **7.2–7.8 s/save** on comparable warmed runs, around a quarter lower overall. The dominant five-session traversal itself fell from roughly **6.6–6.8 s** to about **4.2–4.4 s**, a reduction of roughly one third.

A stage-level optimized run was approximately:

| Stage | Representative elapsed |
| --- | ---: |
| RDA/member read | ~0.01–0.03 s |
| Decompression + `data.bin` write | ~1.5–2.0 s |
| Session location | ~1.4–1.5 s |
| Session parsing | ~4.3 s |
| Canonical normalization | ~0.25 s |
| gzip JSON write | ~0.5–0.6 s |
| One adjacent structural diff | ~0.2 s |

A separate cold-ish `/usr/bin/time -v` one-save comparison measured about **11.2 s → 8.9 s** wall time. Peak RSS was effectively unchanged at roughly **265–266 MiB**, while reported filesystem output fell from roughly **1.0 GiB to 0.55 GiB** because the secondary session blobs were no longer written. The exact values vary with cache and filesystem behavior.

The cold one-save wall reduction is smaller than 25%, while the measured dominant bottleneck is reduced by substantially more than 25% and repeated serial through-parse runs are around the target. The project deliberately stops here rather than adding multiprocessing merely to force a benchmark threshold: bounded parallelism would add memory/progress complexity and should be evaluated independently after serial waste is removed.

## Semantic validation

Two consecutive private saves were re-parsed through the optimized traversal and compared with previously produced baseline state. Session identity, player-area membership, total object counts and every stable `(area_id, object_id, GUID, components)` tuple matched. Transform decoding is independently covered by synthetic regression tests.

Canonical schema v1 and structural-diff payload semantics are unchanged by this optimization.

## Follow-up

Issue #10 provides CLI-level structural-diff timing. In the representative local profile, canonicalization, gzip and a single adjacent diff are materially smaller than session parsing, so #11 does not include speculative diff rewrites or batch parallelism. Future optimization should re-profile real workloads before changing that decision.
