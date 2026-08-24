# Decompression resource validation

Issue #34 requires representative resource evidence in addition to the existing canonical-equality/wall-time check. `decompression_resource_check.py` provides a bounded operator-side measurement for the historical 1 MiB and candidate 16 KiB decompression chunks without changing the production default.

The check requires at least two distinct operator-owned `.a7s` saves. Each source is copied once into a verified temporary snapshot using the same source-before / snapshot / source-after identity check as `decompression_target_check.py`; all measured workers read only those snapshots.

For each chunk size the harness runs the same snapshots with one and two concurrent parser worker subprocesses. Comparative repeats must be a positive even number. Reference/candidate batch order alternates A/B then B/A so each chunk size occupies the first and second position equally often.

Each worker uses the normal `canonicalize_save()` path with only `probe.zlib_to_file` redirected to the selected stdlib streaming decompressor. The parent requires deterministic canonical digests within a configuration and exact digest equality between the 1 MiB and 16 KiB configurations.

## Memory metric

The resource sampler is deliberately explicit about the metric it can observe:

- **Linux:** aggregate proportional set size (`pss`) sampled from `/proc/<pid>/smaps_rollup` across active worker subprocesses.
- **Windows:** aggregate process working set (`working_set`) sampled with `GetProcessMemoryInfo` from the standard-library `ctypes` interface.
- Other platforms fail closed rather than relabeling a different metric as PSS/RSS.

The reported peak is the largest sampled sum across active worker subprocesses during one measured batch. It does not include the small parent harness process and should not be presented as an exact whole-system memory measurement. Sampling is periodic, so it is a bounded operational measurement rather than a proof that an instantaneous sub-sample spike could not have been missed.

## Operator command

Run the check separately under each interpreter whose behavior is being reported. For the #34 acceptance boundary that means CPython is required and PyPy is informative where available.

```bash
python decompression_resource_check.py \
  --repeats 4 \
  --output decompression-resource-check.json \
  "/path/to/Autosave 686.a7s" \
  "/path/to/Autosave 687.a7s"
```

On Windows, run the equivalent command with the operator's normal Python executable and report the emitted `working_set` metric as such. Do not translate it into PSS.

The detached JSON report contains only verified source SHA-256 identities/sizes, Python/platform identity, repeat/worker configuration, canonical digests, wall-time samples, peak-memory samples, and the exact memory metric name. Source paths and save filenames are intentionally omitted from the evidence projection.

A successful report establishes deterministic canonical equality and bounded one/two-worker resource observations for the exact source hashes, interpreter, platform, and run. It does not establish cross-machine portability and does not by itself ship the 16 KiB production default. Issue #34 remains open until production wiring is merged and the required representative target evidence is accepted.
