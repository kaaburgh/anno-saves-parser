# ROADMAP

This is the single product roadmap for extraction, semantic reconstruction, coaching evaluation, deterministic analysis, and later collection UX. It is intentionally dependency-driven: parser breadth should expand when evidence from semantic/coaching evaluation justifies it, not toward an open-ended goal of parsing the entire save format.

## Product sequence

```text
reliable structural state
→ semantic timeline MVP
→ prove coaching usefulness on real play history
→ classify coaching failures / blind spots
→ add intent/context
→ add deterministic economic evidence
→ expand extraction/semantics where evidence shows value
→ repeat evaluation
```

The private v0.3.3 corpus summarized in issue #20 is evidence for prioritization, not a committed fixture. It contains 55 canonical states / 54 adjacent diffs, shows module-heavy construction bursts that require aggregation, frequent stable-ID GUID transitions that make provenance valuable, and two observed player-area additions that are now exposed explicitly as raw `area_added` events by `ASP-P2-0`. Do not infer unsupported gameplay semantics from those aggregates.

## Foundation / observable state

### ASP-P0-1 — Dependency-free save parsing and batch CLI

- **Status:** Implemented, validation incomplete
- **Priority:** High
- **Category:** Foundation
- **Execution:** CLOUD
- **Depends on:** none

Parse current `.a7s` saves through RDA, zlib and FileDB v3; discover/sort autosaves by internal timestamp; support the public batch CLI; produce canonical snapshots and raw structural diffs; keep long stages observable.

Independent audit #40 found that the container/ingest path had no committed end-to-end regression despite its load-bearing role. Issue #41 adds a fully synthetic `.a7s` oracle that exercises the real CLI through RDA, zlib, top-level FileDB/session discovery, canonical output, internal-timestamp listing, adjacent diffs, and a genuine two-worker process pool on the existing CI matrix. Issue #43 adds a fail-closed top-level recognition floor: a save with zero recognized `GameSession` descriptors is rejected before canonical output, with a renamed-entry-tag synthetic end-to-end regression. Issue #45 bounds top-level FileDB dictionary offsets, counts, ID tables, and strings to the file data region, matching the already-bounded embedded-session reader and adding focused malformed-input regressions. Issue #47 makes required outer-RDA member selection exact: missing `data.a7s`/named members fail descriptively and duplicate names are rejected as ambiguous instead of silently choosing directory order. Issue #49 makes filesystem-mtime fallback explicit when internal `LastModTime` metadata cannot be read and narrows fallback handling to expected metadata/input parse failures so unexpected exceptions propagate. Issue #53 makes object-level structural-diff session attribution uniform across every producer section and makes GUID enrichment follow event GUID fields rather than a hardcoded section-name allowlist, with producer-to-consumer synthetic regression coverage for the contract boundary. Issue #63 records that the `AreaManager_<N>` suffix ↔ `AreaInfo/PassiveTrade/AreaID` join is currently supported only by parser-model/internal-consistency fixtures rather than independent proprietary-target corroboration, and defines the bounded target check needed to upgrade that evidence. Issue #65 makes fixed-width uint32 FileDB identities fail closed on malformed widths: session GUID/ID, player-area ownership/AreaID, city-name metadata, and object GUIDs require the supported four-byte representation, while the separately observed wider stable object ID remains unchanged; focused synthetic regressions cover zero-length ownership and oversized GUID values. Issue #75 adds a fail-closed recognition floor for the same area-identity join: if both player-owned `AreaID` values and actually observed `AreaManager_<N>` identities are present but completely disjoint, parsing fails before plausible partial canonical state can be published; matching/partial-overlap cases remain allowed and the invariant is not treated as independent target validation. Issue #77 preserves the source of accepted legacy root rotation values (`Rotation` versus `Rotation90`) and rejects objects that expose both source attributes instead of allowing FileDB record order to choose one silently; synthetic fixtures cover both supported single-source forms and the ambiguous dual-source form. Issue #85 adds a finer-grained fail-closed recognition floor: when a structurally observed `GameSessionManager/AreaInfo` container has direct child tag records but none match the currently recognized entry vocabulary, parsing rejects the session before publishing plausible partial area state; a synthetic renamed-entry fixture covers the boundary without claiming that vocabulary occurs on the proprietary target. These changes improve reproducible coverage and fail-closed ingest behavior without establishing real-target correctness; alternative target entry vocabularies and other proprietary-target behavior remain unestablished, so the item remains validation-incomplete.

### ASP-P0-2 — Repository baseline and CI

- **Status:** Completed and verified
- **Priority:** High
- **Category:** Foundation
- **Execution:** CLOUD
- **Depends on:** ASP-P0-1

Maintain regression tests, agent guidance, architecture notes and cross-platform GitHub Actions around the parser baseline.

Issue #67 closes AUDIT-010 by keeping the source policy, generated agent contract, README, and cross-platform CI compile step aligned on every current production Python module (`anno_save_probe.py` and `guid_mapping.py`) before running the full unit suite.

### ASP-P1-1 — Define canonical schema v1

- **Status:** Completed and verified
- **Priority:** High
- **Category:** Observable state
- **Execution:** CLOUD
- **Depends on:** ASP-P0-2

Keep canonical state explicit and versioned, preserving stable identity, session/area ownership and object/component data while excluding volatile parser-only representation.

### ASP-P1-2 — GUID/name provenance layer

- **Status:** Partially implemented
- **Priority:** Critical
- **Category:** Observable state / provenance
- **Execution:** LOCAL ONLY
- **Depends on:** ASP-P1-1

Resolve relevant GUIDs to human-readable names through an explicit provenance-aware mapping without coupling core parsing to downloaded game assets or guesses. Initial scope should prioritize identities needed to interpret high-frequency stable-ID GUID transitions observed in the private evaluation corpus.

The repository defines a dependency-free versioned mapping contract with required source/mapping provenance, exact-only GUID resolution, explicit unresolved names, and structural-diff enrichment that preserves raw numeric GUID identity. The public batch CLI can optionally load one operator-owned mapping before save parsing and enrich only `summary.json` diffs while leaving canonical snapshots unchanged; malformed, incompatible, or unreadable mappings fail closed. Synthetic tests cover mapping validation plus mapped/unmapped CLI behavior.

Source selection is decided: use an operator-owned Anno 1800 installation as the primary evidence source and a pinned `anno-mods/asset-extractor` release or commit to extract/normalize the relevant asset and localization data. Preserve exact game/source hashes plus extractor/converter identity; keep proprietary extracted catalogs outside the repository. Public asset browsers and static community GUID lists remain secondary corroboration rather than primary provenance. An optional exporter provides a deterministic seam from the extractor's resolved asset cache into mapping schema v1 without adding `assetextractor` to normal parser runtime dependencies. Issue #60 extends schema v1 compatibly with structured extractor/converter identities and per-input SHA-256 identities, includes those fields in `mapping_content_hash`, rejects unknown provenance instead of silently dropping it, and exposes matching optional exporter flags. Existing schema-v1 mappings without the structured fields remain accepted. Issue #69 adds a dependency-free provenance preflight that validates the exact mapping bytes it hashes and emits a compact manifest without GUID/name entries; the manifest requires structured extractor/converter/input provenance and explicitly leaves independent corroboration outstanding. Issue #71 adds a strict representative-corroboration verifier that compares operator-supplied independently observed GUID/name pairs by exact equality, binds them to the exact mapping and observation bytes, and records the reference provenance without pretending the tool can prove that source independence. Issue #73 adds a bounded one-shot operator harness that sequences export, provenance preflight, and representative corroboration with per-stage timeouts and emits a safe detached run record after output safety has been established. A new real operator-owned run must populate the material structured provenance and still requires independently acceptable observations/corroboration, so no real Anno GUID/name claim is established yet. See `docs/guid-source-selection.md`.

**Operator handoff:** the blocked line is the real-data evidence step. It requires access to the operator's exact Anno 1800 installation plus the pinned extractor environment described in `docs/guid-source-selection.md`. Prepare representative GUID/name observations from an independently derived reference, then run the bounded `guid_mapping_target_run.py` harness with the structured extractor identity, converter identity, material per-input SHA-256 identities, exact build identity, and explicit runner identity. Return the successful `guid-mapping-target-run.json` plus only the permitted mapping/evidence artifacts; preserve the recorded reference provenance and never return proprietary game data. The individual export/preflight/corroboration CLIs remain available for debugging. No cloud cycle should substitute synthetic evidence for this target run.

### ASP-P2-0 — Player-area lifecycle raw events

- **Status:** Implemented, validation incomplete
- **Priority:** Critical
- **Category:** Structural diff
- **Execution:** CLOUD
- **Depends on:** ASP-P1-1

Emit deterministic observed area-level structural events (for example player-area present→absent / absent→present) before assigning gameplay semantics. Cover synthetic area additions/removals and preserve session/area identity. This closes the observed gap where object additions can appear in a newly present player-owned area without an explicit higher-level raw event.

The implementation emits explicit `area_added` / `area_removed` raw events keyed by canonical session identity plus `area_id`, including deterministic ordering and GUID-less session-map fallback attribution. Area events remain orthogonal to nested object additions/removals and carry no gameplay-semantic interpretation. Issue #58 makes the evidence boundary explicit: `area_added` / `area_removed` describe membership changes in the player-area projection and do not uniquely establish physical area creation/destruction, settlement, conquest, or another target-side cause. Issue #81 preserves an additive canonical-v1 `observed_areas` projection with supported observed owner IDs and emits deterministic `area_owner_changed` raw evidence only when the same observed session/area exists on both sides with different supported owner IDs; duplicate observed area identities fail closed, while missing ownership does not invent a transition. Existing `player_areas`, player-building membership, and projection lifecycle events remain unchanged. Synthetic regression coverage and cross-platform PR CI establish only the parser/model contract; the motivating private transitions and completeness of non-player-area observations have not been independently re-checked as target evidence, so target validation remains incomplete.

## Semantic timeline MVP

### ASP-P2-1 — Object lifecycle semantic diff

- **Status:** Open
- **Priority:** Critical
- **Category:** Semantic reconstruction
- **Execution:** CLOUD
- **Depends on:** ASP-P1-2, ASP-P2-0

Translate deterministic raw object additions/removals/moves/GUID/component changes into evidence-backed lifecycle events while suppressing representation noise. Keep unsupported upgrade/construction interpretations out until provenance establishes them.

### ASP-P2-2 — Cluster modules into construction episodes

- **Status:** Open
- **Priority:** Critical
- **Category:** Semantic reconstruction
- **Execution:** CLOUD
- **Depends on:** ASP-P2-1

Collapse field/module bursts and related infrastructure into higher-level construction episodes so module-heavy transitions are not represented as hundreds of independent player decisions. Use reduced synthetic cases to establish deterministic clustering behavior. Before treating target-derived grouping boundaries as factual construction episodes, corroborate representative private transitions against independently observed or labeled real player actions; until such target-grounded evidence exists, describe target grouping only as a hypothesis or internal-consistency result rather than validated episode semantics.

### ASP-P4-1 — Stable timeline export contract

- **Status:** Open
- **Priority:** Critical
- **Category:** Semantic timeline contract
- **Execution:** CLOUD
- **Depends on:** ASP-P2-2

Define a compact deterministic timeline/episode JSON contract suitable for downstream evaluation. Preserve the boundary between factual reconstruction and later coaching judgement; the parser/timeline layer must not embed probabilistic coaching.

## Coaching usefulness MVP

### ASP-P5-1 — Coaching evaluation protocol and private corpus policy

- **Status:** Open
- **Priority:** Critical
- **Category:** Evaluation
- **Execution:** CLOUD
- **Depends on:** ASP-P4-1

Define a representative private evaluation slice policy, baseline inputs/outputs, and scoring language for useful, incorrect, unsupported/unverifiable, and missing-evidence coaching observations. Do not commit saves, player data, or generated private dumps.

### ASP-P5-2 — Baseline history-only coaching usefulness experiment

- **Status:** Open
- **Priority:** Critical
- **Category:** Coaching evaluation
- **Execution:** LOCAL ONLY
- **Depends on:** ASP-P5-1

Generate and evaluate baseline coaching from deterministic semantic history before intent enrichment, full economic extraction, or live collection. Coaching must acknowledge absent evidence instead of inventing economy or intent. Preserve concrete failures and examples as sanitized aggregate findings or reduced cases.

### ASP-P5-3 — Coaching failure taxonomy and blind-spot backlog

- **Status:** Open
- **Priority:** Critical
- **Category:** Evaluation / prioritization
- **Execution:** CLOUD
- **Depends on:** ASP-P5-2

Classify failures into: missing observation/state extraction; missing semantic reconstruction; missing GUID/game knowledge/provenance; missing player intent/context; missing deterministic calculation; LLM reasoning/coaching failure despite sufficient evidence; and genuinely unknowable from save history. Convert only high-value, bounded evidence gaps into roadmap items and feed results back into subsequent evaluation.

## Intent-aware coaching

### ASP-P6-1 — Intent/context input contract and comparative evaluation

- **Status:** Open
- **Priority:** High
- **Category:** Coaching context
- **Execution:** CLOUD
- **Depends on:** ASP-P5-3

Define a separate intent/context layer after baseline usefulness is measurable, then evaluate which previously classified failures it fixes. Intent/context may influence coaching judgement but must not mutate reconstructed factual episodes.

## Deterministic economic evidence

### ASP-P1-3 — Economy state extraction

- **Status:** Open
- **Priority:** High
- **Category:** Deterministic economy
- **Execution:** CLOUD
- **Depends on:** ASP-P1-1, ASP-P6-1

Extract population/workforce, money/balance, stocks/inventory and production/demand state justified by coaching blind spots. Treat this as deterministic evidence supplied to coaching, not arithmetic delegated to an LLM.

### ASP-P2-3 — Economy deltas and decision episodes

- **Status:** Open
- **Priority:** High
- **Category:** Deterministic economy
- **Execution:** CLOUD
- **Depends on:** ASP-P1-3, ASP-P2-1

Compute deterministic economic deltas/episodes over consecutive saves, including trends or bottleneck/depletion facts only where the extracted state supports them.

### ASP-P1-4 — Trade route extraction

- **Status:** Blocked on target evidence
- **Priority:** Medium
- **Category:** Deterministic economy / logistics
- **Execution:** CLOUD
- **Depends on:** ASP-P5-3

Canonicalize routes, stations, assigned ships, configured goods and useful visit/history state only if a documented `ASP-P5-3` evaluation result identifies logistics visibility as a material coaching blind spot. Completion of `ASP-P5-3` satisfies the graph dependency but does not by itself open this item: the evaluation outcome must explicitly move this item to `Open`, or drop/supersede it if the expected coaching value is not established. This item is retained but is not assumed to be on the critical path before the first usefulness experiment.

## Blind-spot-driven expansion loop

### ASP-P7-1 — Re-evaluate coaching after deterministic evidence changes

- **Status:** Open
- **Priority:** High
- **Category:** Evaluation loop
- **Execution:** CLOUD
- **Depends on:** ASP-P5-3

For each accepted extraction/semantic/calculation improvement: classify the original failure, state why the added deterministic evidence should prevent it, repeat the relevant coaching evaluation, and record whether the failure moved, disappeared, or exposed another gap. Do not create parser breadth without expected coaching value.

## Incremental/live collection

### ASP-P3-1 — Watch mode

- **Status:** Open
- **Priority:** Low
- **Category:** Collection UX
- **Execution:** CLOUD
- **Depends on:** ASP-P5-2

Watch a save directory, wait for a new `.a7s` write to stabilize, process it once, and append to an incremental timeline. This is deliberately sequenced after the first coaching-usefulness experiment: faster ingestion is not the highest product risk before useful advice is demonstrated.

### ASP-P3-2 — Resume/cache semantics

- **Status:** Open
- **Priority:** Low
- **Category:** Collection UX
- **Execution:** CLOUD
- **Depends on:** ASP-P3-1

Skip already processed saves safely using internal metadata/content identity and make interrupted sessions resumable.

## Explicitly deprioritized performance exploration

Issue #17 (opt-in in-memory expanded FileDB parsing) was closed `not_planned` after bounded parallel parsing landed. It is not a current roadmap dependency. Reopen or replace it only if measured evaluation/operational evidence shows temp-I/O or parser throughput is blocking the product sequence above.

## Planning principle

The common roadmap is a feedback graph, not a one-way parser-completeness ladder. After `ASP-P5-3`, new extraction or semantic work should normally be justified by observed failure classes and expected coaching value, then re-evaluated through `ASP-P7-1`. Existing IDs are retained where their bounded outcome remains valid even when priority or dependency changed.
