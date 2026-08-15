# Research provenance

This project was bootstrapped from direct inspection of user-owned Anno 1800 saves plus public community research. Community implementations are used as format orientation and cross-checks; this repository keeps its own minimal parser and does not vendor those tools.

Useful references discovered during feasibility work:

- `anno-mods/FileDBReader` — FileDB/BBDom parsing concepts and version structure.
- `NiHoel/Anno1800SavegameVisualizer` — demonstrated the RDA → zlib → FileDB/save interpretation pipeline and useful high-level entities such as islands, buildings and routes.
- `lysanntranvouez/RDAExplorer` — RDA v2.2 container/header/block structure.

When adding a new format interpretation, record whether it came from:

1. direct observation of local saves;
2. an independently reproducible structural invariant;
3. a public community reference;
4. a hypothesis awaiting validation.

Do not turn a guessed GUID or opaque field into a durable semantic name without provenance.
