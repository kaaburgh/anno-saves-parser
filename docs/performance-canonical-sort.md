# Canonical session sort performance evidence

This note preserves the bounded local evidence behind issue #36, `Avoid unconditional full-session JSON serialization in canonical sort`. It is performance evidence only; production behavior remains defined by `anno_save_probe.py`, and issue #36 remains open until the lazy-tie implementation is integrated into production and its required validation lands.

## Historical experiment

The local prototype was measured against parser revision `b768091e928eda4924066bca609ff2bc926fdf77` on representative private `Autosave 686`. The save and derived state remain private.

Current canonical session ordering uses the primary identity fields `(session_guid, session_id, map)` followed by deterministic full-session JSON as a final tie-breaker. The prototype preserved that ordering but deferred the expensive JSON serialization until two or more sessions actually shared the complete primary identity tuple.

The prototype produced the same canonical-state SHA-256 as the eager implementation on the representative save.

Representative local Linux timings for `build_canonical_state()` after raw sessions were already parsed were:

| Runtime | Eager full-state tie-breaker | Lazy tie-only serialization |
| --- | ---: | ---: |
| CPython 3.13.5 | ~0.15–0.31 s | commonly ~0.06 s after warm-up |
| PyPy 7.3.19 / Python 3.11.11 | ~0.34–0.48 s | ~0.043–0.052 s |

The CPython measurements are noisy but directionally favorable. The PyPy result is more pronounced because parser traversal is already faster there, making unconditional serialization of several MiB of canonical session state a larger stage-level fraction.

These numbers are local evidence, not a cross-machine performance contract and not a Windows benchmark.

## Differential oracle and helper now committed

PR #95 added `tests/test_canonical_session_sort_oracle.py`. The retained eager reference key covers:

- sessions whose primary identities are unique;
- real `(session_guid, session_id, map)` collisions that still require the full-state deterministic JSON tie-breaker;
- null-identity collisions.

The current bounded implementation step adds `canonical_sort.py`, which contains the pure-stdlib lazy-tie ordering helper. The oracle now checks that this helper remains exactly equivalent to the retained eager ordering and verifies that the full-state tie-breaker is not called for unique primary identities while still being called for every member of a real identity collision group.

The helper is intentionally not yet wired into `build_canonical_state()`. Production behavior therefore remains unchanged until the final integration edit lands and crosses its own CI/review boundary.

## Remaining acceptance boundary

Before issue #36 is complete, the production implementation still needs to:

- route canonical session ordering through the committed lazy-tie helper so `json.dumps(session, ...)` is avoided for sessions whose primary identity is unique;
- preserve the exact existing full-state tie-breaker for genuine primary-key collisions;
- keep canonical ordering byte/semantically equivalent to the eager reference across the committed oracle;
- validate canonical-state equality on at least two consecutive private saves when available, without committing private state;
- record representative post-integration before/after canonicalization timing, with CPython as the default-runtime measurement and PyPy as informative evidence;
- remain pure Python/stdlib and leave parser extraction, canonical schema, structural diff semantics, GUID mapping, decompression, worker policy, and public CLI behavior unchanged.

The current evidence supports integrating the committed lazy-tie helper, but it does not by itself establish portable performance gains or replace the required post-change target validation.
