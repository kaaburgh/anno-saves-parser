# Research provenance

This project was bootstrapped from direct inspection of user-owned Anno 1800 saves plus public community research. Community implementations are used as format orientation and cross-checks; this repository keeps its own minimal parser and does not vendor those tools.

Useful references discovered during feasibility work:

- `anno-mods/FileDBReader` — FileDB/BBDom parsing concepts and version structure.
- `NiHoel/Anno1800SavegameVisualizer` — demonstrated the RDA → zlib → FileDB/save interpretation pipeline and useful high-level entities such as islands, buildings and routes.
- `lysanntranvouez/RDAExplorer` — RDA v2.2 container/header/block structure.

## Direct-save transform observations

Private user-owned saves were inspected directly for issue #5; no proprietary save or derived dump is committed.

Observed facts:

- In `Autosave 686.a7s` and `Autosave 687.a7s`, every canonical player-building object across all five sessions has a root-level `Position` attribute with exactly 12 bytes; those bytes decode as three little-endian float32 values (`<fff>`).
- The same pair exposes root-level `Direction` on a subset of player-building objects as exactly 4 bytes decoding as one little-endian float32 value (`<f>`).
- Independent inspection of `Autosave 711.a7s` and `Autosave 712.a7s` reproduced complete 12-byte Position coverage: 37,570 / 37,570 and 37,571 / 37,571 canonical player-building objects respectively.
- `Autosave 711 -> 712` contains one stable object identity `(session_guid=180025, area_id=8836, id=37950331027457, guid=101290)` whose decoded Position changes while identity remains stable, confirming that the raw movement comparison has a real positive case.

The decoded values are preserved as raw transform state. Axis names, coordinate-system meaning, map/grid units, and higher-level gameplay interpretation remain intentionally unspecified.

When adding a new format interpretation, record whether it came from:

1. direct observation of local saves;
2. an independently reproducible structural invariant;
3. a public community reference;
4. a hypothesis awaiting validation.

Do not turn a guessed GUID or opaque field into a durable semantic name without provenance.
