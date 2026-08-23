# Decompression target validation

Issue #34 reduces the compressed-input chunk used while expanding `data.a7s`. Synthetic regression coverage already establishes deterministic decompressed-output equivalence between the historical 1 MiB reference and the 16 KiB candidate. Real-save validation remains private and must not commit saves or derived player state.

`decompression_target_check.py` is a bounded operator-side check for that remaining evidence. It runs the normal canonicalization path with explicit 1 MiB and 16 KiB chunk sizes. Comparative timing requires a positive even repeat count: comparisons are paired and alternate A/B versus B/A order, so each chunk size occupies the first and second position equally often and neither candidate systematically receives the warmer filesystem/page cache or later JIT state. Source saves are opened read-only by the normal parser path and are never modified.

Example:

```bash
python decompression_target_check.py \
  --repeats 4 \
  --output C:/anno-evidence/decompression-target-check.json \
  "C:/Users/<user>/Documents/Anno 1800/accounts/<account>/Autosave 686.a7s" \
  "C:/Users/<user>/Documents/Anno 1800/accounts/<account>/Autosave 687.a7s"
```

The detached JSON record contains only input SHA-256 identities and sizes, Python/platform identity, explicit chunk sizes, canonical-state SHA-256 values and elapsed times. It intentionally omits source paths and save names from its own evidence projection. A run fails if repeated canonical states disagree for one chunk size, if the 1 MiB and 16 KiB canonical digests differ, or if the requested repeat count is not a positive even integer.

This check is evidence for deterministic whole-parser output and a bounded wall-time comparison. Balanced alternating run order reduces systematic warm-cache/JIT ordering bias, but it does not make the timings a cross-machine performance contract. It also does not measure whole-process-tree peak memory and therefore does not replace the PSS/RSS measurements required by #34. On Linux, keep using an external process-tree measurement such as `/usr/bin/time -v` or an equivalent PSS-capable tool for the memory dimension. On Windows, use the available operator-side process-memory measurement and report the metric actually observed rather than translating it into PSS.

The script does not make 16 KiB the production default. Until `anno_save_probe.zlib_to_file()` is changed and revalidated, #34 remains an implementation-plus-target-validation item rather than a completed optimization.
