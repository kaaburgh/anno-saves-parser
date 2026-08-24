# Canonical session sort performance evidence

This note preserves the bounded local evidence behind issue #36, `Avoid unconditional full-session JSON serialization in canonical sort`. Production behavior is defined by `anno_save_probe.py`; the lazy-tie helper is wired into production, while issue #36 remains open until the required operator-owned equality/timing validation is completed and accepted.

## Historical experiment

The local prototype was measured against parser revision `b768091e928eda4924066bca609ff2bc926fdf77` on representative private `Autosave 686`. The save and derived state remain private.

The historical eager ordering used the primary identity fields `(session_guid, session_id, map)` followed by deterministic full-session JSON as a final tie-breaker. The prototype preserved that ordering but deferred the expensive JSON serialization until two or more sessions actually shared the complete primary identity tuple.

The prototype produced the same canonical-state SHA-256 as the eager implementation on the representative save.

Representative local Linux timings for `build_canonical_state()` after raw sessions were already parsed were:

| Runtime | Eager full-state tie-breaker | Lazy tie-only serialization |
| --- | ---: | ---: |
| CPython 3.13.5 | ~0.15–0.31 s | commonly ~0.06 s after warm-up |
| PyPy 7.3.19 / Python 3.11.11 | ~0.34–0.48 s | ~0.043–0.052 s |

The CPython measurements are noisy but directionally favorable. The PyPy result is more pronounced because parser traversal is already faster there, making unconditional serialization of several MiB of canonical session state a larger stage-level fraction.

These numbers are historical local evidence, not post-integration target validation, a cross-machine performance contract, or a Windows benchmark.

## Differential oracle, helper, and production integration

PR #95 added `tests/test_canonical_session_sort_oracle.py`. The retained eager reference key covers:

- sessions whose primary identities are unique;
- real `(session_guid, session_id, map)` collisions that still require the full-state deterministic JSON tie-breaker;
- null-identity collisions.

PR #97 added `canonical_sort.py`, the pure-stdlib lazy-tie ordering helper. The oracle verifies exact equivalence to the retained eager ordering and verifies that the full-state tie-breaker is skipped for unique primary identities while still being applied to every member of a real identity-collision group.

PR #105 routed production `build_canonical_state()` through `sort_canonical_sessions()`. The oracle instruments the production path itself: unique session identities must cause zero full-state tie-breaker calls, while genuine collisions must still invoke the deterministic tie-breaker for every tied session. Canonical schema, parser extraction, structural diff semantics, GUID mapping, decompression, worker policy, and public CLI behavior remain unchanged.

PR #104 added `canonical_sort_target_check.py`, which packages the required operator-owned equality and ordering-stage timing check on at least two distinct private save identities without committing private state. That harness remains the target-validation boundary for the production change; its existence is not evidence that the operator run has occurred.

## Remaining acceptance boundary

The cloud-side implementation and cross-platform synthetic validation have landed. Before issue #36 is complete, the remaining operator-owned evidence is:

- validate canonical-state equality on at least two distinct consecutive private saves when available using the documented target harness, without committing private state;
- record representative post-integration canonical-ordering timing, with CPython as the default-runtime measurement and PyPy as informative evidence where available;
- keep the exact full-state deterministic JSON tie-breaker for genuine primary-key collisions and preserve the current pure-Python/stdlib compatibility boundary.

The historical measurements and committed synthetic oracle support the production integration, but they do not by themselves establish the post-integration private-save result or portable performance gains. Do not close #36 until the target run has produced acceptable sanitized evidence.
