# Audit #40 remediation ledger

This document records the current repository disposition of the findings from independent audit [#40](https://github.com/kaaburgh/anno-saves-parser/issues/40), which was performed against frozen `main@b768091e928eda4924066bca609ff2bc926fdf77` on 2026-08-18.

The audit itself remains historical evidence and is not rewritten. `ROADMAP.md` remains the sole source of truth for current planning state, dependencies, readiness, execution environment, and acceptance criteria. This document is only remediation provenance: it prevents later work from treating every frozen audit finding as still open or, conversely, from treating intentionally outstanding evidence as completed.

## Disposition vocabulary

- **Repository remediation landed** — the concrete repository defect/process inconsistency identified by the frozen audit has a merged bounded remediation.
- **Partially remediated** — bounded safeguards landed, but the audit identified a broader recognition/evidence class that still has explicitly outstanding work.
- **Evidence outstanding** — repository behavior/documentation was reconciled, but proprietary-target corroboration is still deliberately absent.
- **External/process observation retained** — the observation is not something repository code can prove or close by itself.

## Finding ledger

### AUDIT-001 — unrecognised structure can become plausible absence

**Partially remediated.** Issue #43 added a top-level fail-closed floor when zero `GameSession` descriptors are recognized. Issue #75 added a fail-closed guard when observed player `AreaID` values and observed `AreaManager_<N>` identities are both present but completely disjoint. The roadmap intentionally still records finer-grained session recognition as open. Issue #85 now carries the next bounded `AreaInfo` recognition floor: when a `GameSessionManager/AreaInfo` container is structurally observed with direct child tag records but none are recognized as entries, reject the session before canonical publication. This remains synthetic fail-closed parser work rather than proprietary-target validation.

### AUDIT-002 — inconsistent session identity on structural-diff events

**Repository remediation landed.** Issue #53 unified object-event session attribution across producer sections and added producer-to-consumer regression coverage.

### AUDIT-003 — unbounded top-level FileDB dictionary handling

**Repository remediation landed.** Issue #45 brought top-level FileDB dictionary offsets/counts/strings under bounded fail-closed parsing.

### AUDIT-004 — player-area projection conflates presence and ownership transition

**Repository remediation landed; target interpretation remains conservative.** Issue #58 documented the projection semantics, and issue #81 added optional canonical `observed_areas` plus raw `area_owner_changed` evidence while preserving existing `player_areas` compatibility. The raw owner-ID transition still carries no gameplay interpretation.

### AUDIT-005 — no committed end-to-end container/CLI regression

**Repository remediation landed.** Issue #41 added synthetic `.a7s` end-to-end coverage through the real CLI, including internal timestamp ordering and a genuine multi-process worker path. This remains synthetic capability evidence, not proprietary-target validation.

### AUDIT-006 — GUID mapping producer/input provenance was not machine-checkable

**Repository remediation landed; real target evidence remains outstanding.** Issue #60 added structured extractor/converter/input provenance and fail-closed unknown provenance. Issues #69, #71, and #73 added provenance preflight, representative corroboration packaging, and a bounded one-shot operator harness. `ASP-P1-2` remains incomplete until the documented operator-owned run and independently acceptable corroboration actually occur.

### AUDIT-007 — fixed-width integer decoding and rotation-source ambiguity

**Repository remediation landed.** Issue #65 made fixed-width uint32 attributes fail closed on malformed widths while preserving separately supported wider stable object IDs. Issue #77 preserved the source of legacy `Rotation` versus `Rotation90` and rejects simultaneous ambiguous sources instead of resolving by record order.

### AUDIT-008 — roadmap status/execution classification conflated

**Repository remediation landed.** Issue #54 added explicit execution classification, separated `GATED`-style execution concerns from planning status, and recorded the `ASP-P1-2` local/operator handoff. Issue #78 later added the derived root `OPERATOR.md` projection for current human action.

### AUDIT-009 — stale roadmap statement about player-area events

**Repository remediation landed.** Issue #51 reconciled the corpus-prioritization paragraph with the shipped `area_added` / `area_removed` behavior.

### AUDIT-010 — normative compile command omitted a production module

**Repository remediation landed.** Issue #67 aligned source policy, generated agent policy, README, and CI on compiling both current production modules before tests.

### AUDIT-011 — GUID enrichment depended on a hard-coded diff-section list

**Repository remediation landed with AUDIT-002.** Issue #53 made enrichment event-content-driven and added a producer-derived regression so future GUID-bearing sections do not require maintaining a separate section allowlist.

### AUDIT-012 — required RDA members used silent first-match selection

**Repository remediation landed.** Issue #47 requires exactly one required member and produces descriptive failures for missing or duplicate entries.

### AUDIT-013 — internal timestamp fallback was silent and too broad

**Repository remediation landed.** Issue #49 centralized timestamp fallback, reports filesystem-mtime fallback through normal progress output, and limits fallback to expected metadata/input failures rather than swallowing arbitrary exceptions.

### AUDIT-014 — `AreaManager_<N>` ↔ `AreaID` join lacked independent evidence

**Repository safeguard/documentation landed; independent target evidence outstanding.** Issue #63 records the two identity sources and classifies current synthetic fixtures as internal consistency only. Issue #75 adds the bounded disjoint-namespace recognition guard. The relationship is still not promoted to independently corroborated proprietary-target fact.

### AUDIT-015 — independent-review coverage had lapsed while evidence wording stayed strong

**Repository evidence wording reconciled; external/process observation retained.** Issue #56 downgraded `ASP-P2-0` to `Implemented, validation incomplete` and made the missing target/independent evidence explicit. Reviewer independence/configuration remains an external workflow property and is not something repository content can truthfully declare solved merely because later PRs received owner-account verdicts.

## Remaining audit-derived work

The frozen audit no longer represents fifteen simultaneously open repository defects. The material remainder is narrower:

1. **Finer-grained session recognition** under `ASP-P0-1`: issue #85 carries the current bounded `AreaInfo` recognition floor. Top-level zero-session and complete area-identity-disjointness failures are already guarded; #85 still needs implementation and synthetic validation before this repository-side recognition remainder narrows further. It is not proprietary-target validation.
2. **`ASP-P1-2` target evidence:** the exporter, provenance, preflight, corroboration, and one-shot harness are present, but the actual operator-owned target run and independently acceptable GUID/name observations are still outstanding.
3. **Area-identity target corroboration:** the `AreaManager_<N>` ↔ `AreaID` relationship remains internal-consistency evidence until checked independently on the proprietary target.
4. **Reviewer-independence observation:** audit AUDIT-015 remains historical/process evidence unless the external review topology itself supplies a durable, independently distinguishable verdict source.

Open performance issues #34–#37 were not audit-remediation dependencies and remain governed by the roadmap's explicit deprioritization rather than this ledger.

## Audit issue lifecycle

Audit #40 is closed as a completed historical audit. That closure records that the frozen audit has been triaged and its remaining work is represented by the live roadmap, operator handoff, this ledger, and explicit follow-up issues such as #85. It does **not** mean the outstanding target evidence, remaining recognition work, or external reviewer-independence observation is complete.