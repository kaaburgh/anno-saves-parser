# Canonical session sort target validation

Issue #36 already has a committed synthetic differential oracle and an isolated lazy-session-sort helper. This operator-side harness packages the remaining private-save equality and ordering-timing evidence without committing proprietary save data or changing production behavior.

## Run

Use at least two consecutive operator-owned `.a7s` saves. The default repeat count is four; repeat counts must be positive and even so eager/lazy ordering timings receive the same number of first and second positions.

```bash
python canonical_sort_target_check.py \
  "C:/AnnoEvidence/Autosave 686.a7s" \
  "C:/AnnoEvidence/Autosave 687.a7s" \
  --repeats 4 \
  --output "C:/AnnoEvidence/canonical-sort-target-check.json"
```

The source saves are treated as read-only evidence. Each save is copied into a temporary verified snapshot before parsing; the source hash/size before the copy, snapshot identity and source identity after the copy must agree. The detached evidence output is rejected if it aliases a source save and is published with an atomic same-directory replacement.

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

A successful report establishes equality and ordering-stage timing only for the exact source hashes and environment recorded. It does not establish cross-machine or Windows performance portability, and it does not by itself make the lazy helper the production path.

## Remaining #36 boundary

After acceptable target evidence, issue #36 still requires wiring `sort_canonical_sessions()` into production `build_canonical_state()`, preserving the committed differential oracle, running cross-platform CI on that exact integration head, and recording representative post-integration timing before the issue can be treated as complete.
