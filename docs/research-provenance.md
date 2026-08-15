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

When adding a new format interpretation, record whether it came from:

1. direct observation of local saves;
2. an independently reproducible structural invariant;
3. a public community reference;
4. a hypothesis awaiting validation.

Do not turn a guessed GUID or opaque field into a durable semantic name without provenance.
