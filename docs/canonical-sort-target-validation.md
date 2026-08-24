# Canonical session sort target validation

Issue #36 has a committed synthetic differential oracle, an isolated lazy-session-sort helper, and production wiring through `build_canonical_state()`. This operator-side harness packages the remaining private-save equality and ordering-timing evidence without committing proprietary save data.

## Run

Use at least two consecutive operator-owned `.a7s` saves with distinct source paths and distinct source contents. The default repeat count is four; repeat counts must be positive and even so eager/lazy ordering timings receive the same number of first and second positions.

```bash
python canonical_sort_target_check.py \
  "C:/AnnoEvidence/Autosave 686.a7s" \
  "C:/AnnoEvidence/Autosave 687.a7s" \
  --repeats 4 \
  --output "C:/AnnoEvidence/canonical-sort-target-check.json"
```

The source saves are treated as read-only evidence. Each save is copied into a temporary verified snapshot before parsing; the source hash/size before the copy, snapshot identity and source identity after the copy must agree. Duplicate resolved source paths and duplicate source SHA-256 identities fail closed so one save cannot satisfy the two-save validation boundary twice. The detached evidence output is rejected if it aliases a source save and is published with an atomic same-directory replacement.

## Oracle

For each verified snapshot, the harness runs the normal RDA/zlib/FileDB parsing path to obtain raw parsed sessions. It then:

1. builds the current production canonical state as the reference;
2. projects each session independently, excluding production multi-session ordering from the candidate input;
3. compares the retained eager full-state sort key with `canonical_sort.sort_canonical_sessions()`;
4. requires deterministic results across repeats;
5. requires exact candidate/reference session ordering and exact candidate/current-production canonical state equality.

Ordering timings use balanced alternating pairs: eager→lazy, then lazy→eager. They measure only the session-ordering stage over already projected canonical sessions, not whole-save parse wall time. This keeps the timing claim aligned with the optimization seam and avoids conflating parser/decompression noise with canonical ordering cost.

## Evidence record

The JSON report records:

- schema/version and runner identity;
- Python implementation/version and platform;
- repeat count and timing-order policy;
- per-save source SHA-256 and byte size, but no source path or save filename;
- session count and deterministic canonical-state SHA-256;
- per-repeat eager-reference and lazy-candidate ordering times.

A successful report establishes equality and ordering-stage timing only for the exact distinct source hashes and environment recorded. It does not establish cross-machine or Windows performance portability. The lazy helper is already the production path; the harness exists to validate that production optimization on private target evidence, not to gate whether the helper is wired.

## Remaining #36 boundary

Production lazy-sort integration and its cross-platform synthetic CI have already landed via PR #105. Issue #36 remains open only for the operator-owned target evidence:

- validate canonical-state equality on at least two distinct consecutive private saves using this harness, without committing private state;
- record representative post-integration canonical-ordering timing, with CPython as the default-runtime measurement and PyPy as informative evidence where available;
- preserve the exact full-state deterministic JSON tie-breaker for genuine primary-key collisions and treat the existing synthetic oracle as capability/regression evidence rather than a substitute for the private run.

Do not close #36 merely because this harness exists or because historical pre-integration measurements were favorable; completion requires the post-integration target run and accepted sanitized evidence.
