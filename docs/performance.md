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


## Bounded batch parallelism (#16)

After the serial traversal work above, independent saves are the dominant batch-level parallelism boundary. Version 0.4.0 therefore adds explicit `--workers N` process workers while deliberately keeping the default at `1`. Automatic fan-out is not enabled: each active save expands one roughly 268 MiB `data.bin` in the representative corpus and carries substantial parser/mmap state, so an implicit CPU-count default could create surprising RAM and temporary-storage pressure on Windows machines.

The scheduler submits at most the resolved worker count at once, returns canonical states to their original chronological slots, writes each canonical file by source identity, and only builds adjacent diffs after all selected saves complete. Worker-internal progress is suppressed in parallel mode; the parent reports aggregate completed/running/pending counts and durable per-save completion lines. `--workers 1` retains the existing detailed serial stage output.

### Local private-save scaling measurement

A four-save consecutive private subset was measured in the implementation runtime using the optimized bounded-mmap traversal and the same process-per-save orchestration. This runtime reported 5 logical CPUs. The values are local evidence, not a cross-machine performance contract and not a substitute for the earlier Windows 55-save baseline.

| Workers | Wall time | Saves/s | Approx active `data.bin` upper bound | Approx active-worker RSS upper bound |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 33.9 s | 0.118 | 268 MiB | 281 MiB |
| 2 | 18.0 s | 0.223 | 536 MiB | 493 MiB |
| 4 | 10.8 s | 0.370 | 1,071 MiB | 910 MiB |

On the same two-save pair, a separate check measured 16.59 s with one worker versus 8.78 s with two workers (~1.89x). Four workers continue to improve throughput in this runtime, but resource pressure scales roughly with active saves and the per-save time itself rises modestly under contention. That tradeoff is why 0.4.0 requires explicit opt-in rather than selecting `os.cpu_count()` automatically.

Peak RSS was sampled per worker with the platform `resource` API in this Linux runtime; the aggregate values above are conservative sums of the largest simultaneously active worker peaks, not a synchronized whole-process-tree measurement. Temp pressure is the sum of representative expanded `data.bin` sizes. Windows behavior can differ because process spawn, filesystem, antivirus and page-cache behavior differ; users should benchmark `1`, `2`, and `4` on their own machine before adopting a larger persistent setting.

The CLI can query available physical memory through Win32 `GlobalMemoryStatusEx` or POSIX `sysconf` when available, plus free temporary-filesystem space through the standard library. These checks intentionally produce warnings rather than hard caps because the fixed per-worker values are measurements/estimates, not a proof that a particular save will or will not fit. Explicit `--workers N` remains user-controlled, except for the standard-library Windows `ProcessPoolExecutor` hard maximum of 61 active workers, which is validated before pool construction.

## Decompression input chunk investigation (#34)

Issue #34 records a bounded local experiment on two consecutive private saves using the parsing core at `main@b768091e928eda4924066bca609ff2bc926fdf77`. The experiment compared the current 1 MiB compressed-input step in `zlib_to_file()` with a 16 KiB candidate. The saves and derived state remain private; these measurements are local Linux x86-64 evidence, not a cross-machine or Windows performance contract.

Representative measurements were:

| Runtime / workload | 1 MiB input chunk | 16 KiB input chunk | Observed effect |
| --- | ---: | ---: | ---: |
| CPython 3.13.5, 1 save | ~5.84 s / ~219 MiB peak PSS | ~5.35 s / ~195 MiB | ~8% lower wall, ~11% lower PSS |
| PyPy 7.3.19, 1 save | ~2.43 s / ~316 MiB | ~2.16 s / ~191 MiB | ~11% lower wall, ~39% lower PSS |
| CPython, 2 workers | ~6.59 s / ~395 MiB | ~6.23 s / ~394 MiB | wall slightly lower, PSS roughly neutral |
| PyPy, 2 workers | ~3.45 s / ~592 MiB | ~2.99 s / ~409 MiB | ~13% lower wall, ~31% lower PSS |
| CPython, 4-worker stress | ~7.15 s / ~699 MiB | ~7.10 s / ~674 MiB | wall neutral, modest PSS reduction |
| PyPy, 4-worker stress | ~3.96 s / ~1043 MiB | ~3.78 s / ~739 MiB | ~5% lower wall, ~29% lower PSS |

The four-worker measurements reused the same two private saves under distinct local names to stress resource scaling; they are throughput/resource evidence only, not four independent semantic fixtures. A separate 1–64 KiB sweep found a broad fast plateau rather than a unique optimum. The existing evidence therefore supports 16 KiB as a conservative implementation candidate because it captures the observed memory reduction without demonstrating a throughput advantage for retaining 1 MiB.

This section preserves the evidence; it does **not** mark #34 implemented. The repository still uses the 1 MiB input step. Before closing #34, the production change still needs a named internal chunk constant, differential deterministic-output regression coverage, representative private-save comparison against the 1 MiB baseline for CPython workers 1/2 (with PyPy informative where available), and conservative reporting of any Windows real-save measurements. No public chunk-size tuning flag is justified by the current evidence.
