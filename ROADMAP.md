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

The private v0.3.3 corpus summarized in issue #20 is evidence for prioritization, not a committed fixture. It contains 55 canonical states / 54 adjacent diffs, shows module-heavy construction bursts that require aggregation, frequent stable-ID GUID transitions that make provenance valuable, and two observed player-area additions that current raw structural diffs do not expose explicitly. Do not infer unsupported gameplay semantics from those aggregates.

## Foundation / observable state

### ASP-P0-1 — Dependency-free save parsing and batch CLI

- **Status:** Completed and verified
- **Priority:** High
- **Category:** Foundation
- **Depends on:** none

Parse current `.a7s` saves through RDA, zlib and FileDB v3; discover/sort autosaves by internal timestamp; support the public batch CLI; produce canonical snapshots and raw structural diffs; keep long stages observable.

### ASP-P0-2 — Repository baseline and CI

- **Status:** Completed and verified
- **Priority:** High
- **Category:** Foundation
- **Depends on:** ASP-P0-1

Maintain regression tests, agent guidance, architecture notes and cross-platform GitHub Actions around the parser baseline.

### ASP-P1-1 — Define canonical schema v1

- **Status:** Completed and verified
- **Priority:** High
- **Category:** Observable state
- **Depends on:** ASP-P0-2

Keep canonical state explicit and versioned, preserving stable identity, session/area ownership and object/component data while excluding volatile parser-only representation.

### ASP-P1-2 — GUID/name provenance layer

- **Status:** Partially implemented
- **Priority:** Critical
- **Category:** Observable state / provenance
- **Depends on:** ASP-P1-1

Resolve relevant GUIDs to human-readable names through an explicit provenance-aware mapping without coupling core parsing to downloaded game assets or guesses. Initial scope should prioritize identities needed to interpret high-frequency stable-ID GUID transitions observed in the private evaluation corpus.

The first implementation slice defines a dependency-free versioned mapping contract with required source/mapping provenance, exact-only GUID resolution, explicit unresolved names, and structural-diff enrichment that preserves raw numeric GUID identity. Synthetic tests cover resolved, unknown, malformed and incompatible-provenance cases. CLI wiring and a documented operator-owned real mapping source remain open; no real Anno GUID/name claim is established yet.

### ASP-P2-0 — Player-area lifecycle raw events

- **Status:** Completed and verified
- **Priority:** Critical
- **Category:** Structural diff
- **Depends on:** ASP-P1-1

Emit deterministic observed area-level structural events (for example player-area present→absent / absent→present) before assigning gameplay semantics. Cover synthetic area additions/removals and preserve session/area identity. This closes the observed gap where object additions can appear in a newly present player-owned area without an explicit higher-level raw event.

The implementation emits explicit `area_added` / `area_removed` raw events keyed by canonical session identity plus `area_id`, including deterministic ordering and GUID-less session-map fallback attribution. Area events remain orthogonal to nested object additions/removals and carry no gameplay-semantic interpretation. Synthetic regression coverage and the durable raw-diff contract are present. GitHub Actions PR CI associated with the implementation head verified the generated merge ref against the current base across Python 3.11 and 3.14 on Ubuntu and Windows; the final roadmap-only reconciliation is subject to the same PR CI gate before merge.

## Semantic timeline MVP

### ASP-P2-1 — Object lifecycle semantic diff

- **Status:** Open
- **Priority:** Critical
- **Category:** Semantic reconstruction
- **Depends on:** ASP-P1-2, ASP-P2-0

Translate deterministic raw object additions/removals/moves/GUID/component changes into evidence-backed lifecycle events while suppressing representation noise. Keep unsupported upgrade/construction interpretations out until provenance establishes them.

### ASP-P2-2 — Cluster modules into construction episodes

- **Status:** Open
- **Priority:** Critical
- **Category:** Semantic reconstruction
- **Depends on:** ASP-P2-1

Collapse field/module bursts and related infrastructure into higher-level construction episodes so module-heavy transitions are not represented as hundreds of independent player decisions. Use reduced synthetic cases to establish deterministic clustering behavior. Before treating target-derived grouping boundaries as factual construction episodes, corroborate representative private transitions against independently observed or labeled real player actions; until such target-grounded evidence exists, describe target grouping only as a hypothesis or internal-consistency result rather than validated episode semantics.

### ASP-P4-1 — Stable timeline export contract

- **Status:** Open
- **Priority:** Critical
- **Category:** Semantic timeline contract
- **Depends on:** ASP-P2-2

Define a compact deterministic timeline/episode JSON contract suitable for downstream evaluation. Preserve the boundary between factual reconstruction and later coaching judgement; the parser/timeline layer must not embed probabilistic coaching.

## Coaching usefulness MVP

### ASP-P5-1 — Coaching evaluation protocol and private corpus policy

- **Status:** Open
- **Priority:** Critical
- **Category:** Evaluation
- **Depends on:** ASP-P4-1

Define a representative private evaluation slice policy, baseline inputs/outputs, and scoring language for useful, incorrect, unsupported/unverifiable, and missing-evidence coaching observations. Do not commit saves, player data, or generated private dumps.

### ASP-P5-2 — Baseline history-only coaching usefulness experiment

- **Status:** Open
- **Priority:** Critical
- **Category:** Coaching evaluation
- **Depends on:** ASP-P5-1

Generate and evaluate baseline coaching from deterministic semantic history before intent enrichment, full economic extraction, or live collection. Coaching must acknowledge absent evidence instead of inventing economy or intent. Preserve concrete failures and examples as sanitized aggregate findings or reduced cases.

### ASP-P5-3 — Coaching failure taxonomy and blind-spot backlog

- **Status:** Open
- **Priority:** Critical
- **Category:** Evaluation / prioritization
- **Depends on:** ASP-P5-2

Classify failures into: missing observation/state extraction; missing semantic reconstruction; missing GUID/game knowledge/provenance; missing player intent/context; missing deterministic calculation; LLM reasoning/coaching failure despite sufficient evidence; and genuinely unknowable from save history. Convert only high-value, bounded evidence gaps into roadmap items and feed results back into subsequent evaluation.

## Intent-aware coaching

### ASP-P6-1 — Intent/context input contract and comparative evaluation

- **Status:** Open
- **Priority:** High
- **Category:** Coaching context
- **Depends on:** ASP-P5-3

Define a separate intent/context layer after baseline usefulness is measurable, then evaluate which previously classified failures it fixes. Intent/context may influence coaching judgement but must not mutate reconstructed factual episodes.

## Deterministic economic evidence

### ASP-P1-3 — Economy state extraction

- **Status:** Open
- **Priority:** High
- **Category:** Deterministic economy
- **Depends on:** ASP-P1-1, ASP-P6-1

Extract population/workforce, money/balance, stocks/inventory and production/demand state justified by coaching blind spots. Treat this as deterministic evidence supplied to coaching, not arithmetic delegated to an LLM.

### ASP-P2-3 — Economy deltas and decision episodes

- **Status:** Open
- **Priority:** High
- **Category:** Deterministic economy
- **Depends on:** ASP-P1-3, ASP-P2-1

Compute deterministic economic deltas/episodes over consecutive saves, including trends or bottleneck/depletion facts only where the extracted state supports them.

### ASP-P1-4 — Trade route extraction

- **Status:** GATED
- **Priority:** Medium
- **Category:** Deterministic economy / logistics
- **Depends on:** ASP-P5-3

Canonicalize routes, stations, assigned ships, configured goods and useful visit/history state only if a documented `ASP-P5-3` evaluation result identifies logistics visibility as a material coaching blind spot. Completion of `ASP-P5-3` satisfies the graph dependency but does not by itself open this item: the evaluation outcome must explicitly move this item to `Open`, or drop/supersede it if the expected coaching value is not established. This item is retained but is not assumed to be on the critical path before the first usefulness experiment.

## Blind-spot-driven expansion loop

### ASP-P7-1 — Re-evaluate coaching after deterministic evidence changes

- **Status:** Open
- **Priority:** High
- **Category:** Evaluation loop
- **Depends on:** ASP-P5-3

For each accepted extraction/semantic/calculation improvement: classify the original failure, state why the added deterministic evidence should prevent it, repeat the relevant coaching evaluation, and record whether the failure moved, disappeared, or exposed another gap. Do not create parser breadth without expected coaching value.

## Incremental/live collection

### ASP-P3-1 — Watch mode

- **Status:** Open
- **Priority:** Low
- **Category:** Collection UX
- **Depends on:** ASP-P5-2

Watch a save directory, wait for a new `.a7s` write to stabilize, process it once, and append to an incremental timeline. This is deliberately sequenced after the first coaching-usefulness experiment: faster ingestion is not the highest product risk before useful advice is demonstrated.

### ASP-P3-2 — Resume/cache semantics

- **Status:** Open
- **Priority:** Low
- **Category:** Collection UX
- **Depends on:** ASP-P3-1

Skip already processed saves safely using internal metadata/content identity and make interrupted sessions resumable.

## Explicitly deprioritized performance exploration

Issue #17 (opt-in in-memory expanded FileDB parsing) was closed `not_planned` after bounded parallel parsing landed. It is not a current roadmap dependency. Reopen or replace it only if measured evaluation/operational evidence shows temp-I/O or parser throughput is blocking the product sequence above.

## Planning principle

The common roadmap is a feedback graph, not a one-way parser-completeness ladder. After `ASP-P5-3`, new extraction or semantic work should normally be justified by observed failure classes and expected coaching value, then re-evaluated through `ASP-P7-1`. Existing IDs are retained where their bounded outcome remains valid even when priority or dependency changed.