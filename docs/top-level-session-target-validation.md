# Top-level session scanner target validation

Issue #35 replaces the hot buffered top-level FileDB traversal with a read-only mmap/offset scanner. The repository already contains a synthetic differential oracle and the isolated mmap scanner. This operator-side harness packages the remaining private-save descriptor-equivalence and timing check without committing proprietary saves or expanded FileDB data.

The harness deliberately compares the mmap scanner with a retained buffered reference scanner rather than with production `extract_sessions()`. That keeps the evidence path independent after production eventually switches to mmap; the buffered implementation is evidence/test-only and is not a second public parser mode.

## Run

Use at least two **distinct** consecutive operator-owned `.a7s` saves. The harness rejects duplicate resolved paths and also rejects different paths whose verified snapshots have identical SHA-256 content, so one save identity cannot satisfy the two-save evidence boundary twice.

```powershell
python .\top_level_session_target_check.py `
  "C:\...\Autosave 686.a7s" `
  "C:\...\Autosave 687.a7s" `
  --repeats 4 `
  --output "C:\anno-evidence\top-level-session-target-check.json"
```

`--repeats` must be a positive even integer. Each repeat runs both implementations, alternating buffered→mmap and mmap→buffered order so neither scanner systematically receives the warmer position.

For each source save, the harness first creates a temporary verified snapshot. It hashes and sizes the live source before copying, hashes and sizes the snapshot, then hashes and sizes the live source again; any disagreement fails closed. Parsing and both scanners operate only on the verified snapshot, so descriptor/timing evidence and the reported source identity are bound to the same bytes while the operator-owned source remains read-only.

The harness expands the snapshot's `data.a7s` only inside the same temporary directory, reads FileDB metadata through the existing parser metadata path, then compares the retained buffered reference scanner with `scan_top_level_sessions_mmap()` using that same metadata.

## Success and failure oracle

For every supplied save, each implementation must be deterministic across repeats and the final descriptor lists must compare exactly, including ordering, `binary_offset`, `binary_size`, GUID/ID/map metadata and omission/presence of optional fields. Any mismatch fails the run.

The detached JSON report records only:

- SHA-256 and size for the verified source snapshot, without path or filename;
- Python implementation/version and platform facts;
- the balanced repeat count/order;
- descriptor count and deterministic descriptor SHA-256;
- per-run buffered-reference and mmap traversal wall times.

The output path may not alias a source save and publication uses an atomic same-directory replacement.

## Evidence boundary

A successful report establishes descriptor equivalence and representative scanner timing on the exact **distinct** verified source bytes named by their hashes. Supplying the same path twice or supplying byte-identical saves through different paths fails closed rather than manufacturing two-save evidence. Because the buffered reference is retained independently of production `extract_sessions()`, the differential oracle remains meaningful after production wiring. The report does not establish broader canonical-state semantics, decompression behavior, GUID interpretation, or cross-machine performance.

Issue #35 still requires the production `extract_sessions()` wiring to the mmap helper. The historical Linux measurements remain local evidence, and Windows portability/resource behavior must still be checked conservatively before treating exact performance numbers as portable.
