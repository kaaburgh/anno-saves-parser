# Current operator handoff

This file is a derived projection of the current human action in [`ROADMAP.md`](./ROADMAP.md). The roadmap remains authoritative for planning state, dependencies, readiness, and sequencing. If this projection disagrees with the roadmap, follow the roadmap.

## Current action — ASP-P1-2 GUID/name target evidence

`ASP-P1-2` is currently `Partially implemented` and `LOCAL ONLY`. Cloud tooling for export, provenance preflight, representative corroboration, and the bounded one-shot run is prepared; the remaining step requires the operator-owned exact Anno 1800 installation.

Before running anything, prepare representative GUID/name observations from a reference that is independently acceptable from the primary extractor/catalog path. The verifier can check exact agreement and bind reference provenance, but it cannot prove that the supplied reference is independent.

Use the one-shot runner described in [`docs/guid-source-selection.md`](./docs/guid-source-selection.md):

```text
python guid_mapping_target_run.py \
  --asset-extractor-root C:/tools/asset-extractor \
  --config C:/tools/asset-extractor/config.json \
  --observations C:/anno-evidence/guid-mapping-observations.json \
  --output-dir C:/anno-evidence/run-001 \
  --runner-identity anno-saves-parser/guid_mapping_target_run.py@<commit> \
  --source-version <exact-game-build> \
  --source-hash sha256:<manifest-digest> \
  --mapping-version guid-map-<revision> \
  --extractor-identity anno-mods/asset-extractor@<release-or-commit> \
  --extractor-artifact-hash sha256:<optional-extractor-artifact-digest> \
  --converter-identity anno-saves-parser/guid_mapping_export.py@<commit> \
  --converter-artifact-hash sha256:<optional-converter-artifact-digest> \
  --input-hash assets=sha256:<assets-input-digest> \
  --input-hash localization-en=sha256:<localization-input-digest>
```

Use [`docs/guid-source-selection.md`](./docs/guid-source-selection.md) as the durable contract for observation format, provenance fields, safety rules, failure handling, and the individual recovery/debugging commands.

## Evidence boundary

A successful run should produce the bounded mapping/provenance/corroboration artifacts described by the durable procedure. Return or retain only those permitted derived evidence artifacts; do not commit or package proprietary game assets, extracted catalogs, private target payloads, or unrelated host data.

A successful harness run is not by itself a validated real GUID/name claim. The recorded reference provenance and representative corroboration still need independent acceptance before `ASP-P1-2` can advance and before dependent `ASP-P2-1` becomes ready.

## No other current human action

Blocked downstream items and cloud-executable work are intentionally omitted from this projection. Reconcile this file whenever the current operator action or its procedure changes.
