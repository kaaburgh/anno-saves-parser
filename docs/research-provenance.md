# Research provenance

This project was bootstrapped from direct inspection of user-owned Anno 1800 saves plus public community research. Community implementations are used as format orientation and cross-checks; this repository keeps its own minimal parser and does not vendor those tools.

Useful references discovered during feasibility work:

- `anno-mods/FileDBReader` — FileDB/BBDom parsing concepts and version structure.
- `NiHoel/Anno1800SavegameVisualizer` — demonstrated the RDA → zlib → FileDB/save interpretation pipeline and useful high-level entities such as islands, buildings and routes.
- `lysanntranvouez/RDAExplorer` — RDA v2.2 container/header/block structure.

## Direct-save transform observations

Private user-owned saves were inspected directly for issue #5; no proprietary save, generated dump, object identifier, or exact player-state value is committed.

Observed facts reduced to structural invariants:

- Canonical player-building objects expose root-level `Position` as exactly 12 bytes decoding as three little-endian float32 values (`<fff>`).
- The same root structure exposes optional `Direction` as exactly 4 bytes decoding as one little-endian float32 value (`<f>`).
- The Position representation was observed consistently across multiple consecutive private-save pairs and across all observed sessions.
- At least one stable object identity changed decoded Position between consecutive saves without becoming an add/remove pair, providing a positive raw movement case.

The decoded values are preserved as raw transform state. Axis names, coordinate-system meaning, map/grid units, and higher-level gameplay interpretation remain intentionally unspecified.

## Player-area identity join

Player-area extraction currently combines two separately decoded structural sources into one area-identity space:

- object attribution comes from numeric suffixes of `AreaManager_<N>` tag names;
- ownership attribution comes from `AreaInfo` → `PassiveTrade` → `AreaID` attribute values.

The parser joins those values as the same `area_id`. Current committed synthetic fixtures deliberately use matching values in both structures, so they establish internal consistency of the implementation and regression contract only. They are **not** independent corroboration that both structures use the same identifier space on the proprietary target. Until independently checked, treat that relationship as an assumption supported by the parser model rather than a separately established target fact.

Issue #75 adds a bounded recognition floor around that assumption: when both player-owned `AreaID` values and actually observed `AreaManager_<N>` identities are present in one parsed session, a completely disjoint pair of sets is rejected explicitly before canonical state can be published. Partial overlap remains accepted, and absence of either set does not by itself prove corruption. This fail-closed invariant prevents one demonstrated plausible-partial-state failure mode; it does **not** upgrade the identity join from internal-consistency evidence to an independently established target fact.

A bounded target check can upgrade the evidence without committing private data: on exact operator-owned save inputs, independently collect the set of observed `AreaManager_<N>` suffixes and the set of `AreaInfo/PassiveTrade/AreaID` values for the same sessions, preserve only safe aggregate relationship evidence plus target/tool provenance, and verify representative overlap/join behavior. Exact player-state identifiers, save payloads, and private dumps remain local. A synthetic fixture generated from the same parser model does not count as that independent check.

When adding a new format interpretation, record whether it came from:

1. direct observation of local saves;
2. an independently reproducible structural invariant;
3. a public community reference;
4. a hypothesis awaiting validation.

Do not turn a guessed GUID or opaque field into a durable semantic name without provenance.
