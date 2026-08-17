# GUID source selection

This document records the source/acquisition decision for real Anno 1800 GUID/name evidence under `ASP-P1-2`. It complements the mapping format and consumer contract in [`guid-mapping.md`](./guid-mapping.md); it does not establish any particular GUID/name pair by itself.

## Decision

Use an **operator-owned Anno 1800 installation** as the primary source of real GUID/name evidence. Extract and normalize the relevant asset/localization data locally with a **pinned `anno-mods/asset-extractor` release or commit**. Do not download or commit extracted proprietary catalogs merely to populate names.

As of this investigation, `anno-mods/asset-extractor` release `3.0` is the current published release inspected. Its documentation states that it extracts from the configured local game installation, parses Anno 1800 `assets.xml`, resolves asset structure, and supports localization. The extractor code is MIT-licensed. Those facts make it a suitable reproducible acquisition/normalization tool, while the game files and extracted data remain separate operator-owned proprietary inputs.

This is a source-path decision, not target validation. A real mapping still requires an operator run against an exact game installation plus validation of the resulting mapping evidence.

## Why this source wins

The mapping contract requires evidence that can be bound to the exact material inputs that determine interpretation. A local installed-game source can supply that boundary: exact game/build identity, hashes of the extracted asset/localization inputs used for the mapping, and the exact extractor release/commit that normalized them.

That is stronger provenance than a convenient public lookup whose backend data revision, extraction procedure, and game-build identity may not be independently pinned by this repository.

## Secondary references

Public community resources remain useful for investigation and independent spot checks, but they are not the primary source of mapping provenance:

- the Anno modding guide documents `assets.xml` as the central asset-definition surface and points modders to asset-search tooling;
- `a1800.net` is a practical GUID/asset browser referenced by the community guide;
- static community GUID lists can provide human-readable cross-check candidates.

A match against one of these references may corroborate an operator-derived result. It must not silently replace exact-build/source provenance, and disagreement remains explicit evidence to investigate rather than a reason to choose whichever name is convenient.

## Required provenance for a real mapping run

Before names produced through this path are treated as real target evidence, preserve enough information to reject stale or semantically incompatible output:

1. exact Anno 1800 game/build identity available to the operator;
2. SHA-256 identities for every extracted asset/localization input that materially affects GUID/name interpretation;
3. exact `anno-mods/asset-extractor` release or commit identity and, when practical, the acquired artifact digest;
4. converter/export implementation identity used to produce mapping schema v1;
5. the mapping schema/version plus the generated `mapping_content_hash` already enforced by `guid_mapping.py`.

The repository should consume only the resulting small provenance-aware mapping document when the operator is entitled to retain/share it. Raw RDA content, extracted proprietary XML/catalogs, private saves, and unrelated extracted assets stay outside the repository.

## Bounded exporter

`guid_mapping_export.py` is an optional operator-side adapter. The normal save parser never imports `assetextractor`; the third-party package is loaded only when this exporter is invoked explicitly against a pinned checkout whose environment is already installed.

The adapter reads the resolved `AssetCache`, uses the requested localized text when present, falls back only to the extractor's own stable asset name, skips assets for which neither exists, sorts output by numeric GUID, and fails closed on invalid GUIDs, conflicting duplicate GUID/name pairs, malformed provenance, or an empty result. It does not infer a nearby or likely name.

Before running it, create a small local manifest that records every extracted asset/localization input material to GUID/name interpretation and hash that manifest with SHA-256. The manifest itself may contain local paths or proprietary filenames and therefore remains operator-owned; only its digest needs to enter the mapping document. Use a `mapping_version` that names both the pinned extractor revision and this exporter revision, for example `asset-extractor@3.0+guid-export-v1`.

Choose an output path separate from the pinned extractor checkout and all source paths in its config. The exporter rejects an output that overwrites the config itself or falls within the configured `game_path`, `cache_path`, or `assetbrowser_dir`, and it also protects the extractor checkout. After the mapping document is fully built and validated, it is published through an atomic same-directory replacement so an interrupted write cannot leave a partial mapping at the requested path.

Example, from an environment where the pinned extractor checkout has already completed its documented extraction/setup:

```text
python guid_mapping_export.py \
  --asset-extractor-root C:/tools/asset-extractor \
  --config C:/tools/asset-extractor/config.json \
  --output C:/private/anno1800-guid-mapping.json \
  --language english \
  --source-version <exact-game-build> \
  --source-hash sha256:<manifest-digest> \
  --mapping-version asset-extractor@3.0+guid-export-v1
```

The output is mapping schema v1 and can be passed to the batch parser with `--guid-mapping`. Keep the generated mapping private unless the operator is entitled to retain/share its derived names. The export command itself does **not** establish a real target claim; that requires executing it on the operator-owned installation, preserving the stated provenance, and independently checking representative GUID/name pairs or another relationship that does not reuse the same derivation.

## Follow-up boundary

Source selection and a deterministic converter/export seam are now prepared, but `ASP-P1-2` is not complete. The remaining bounded evidence step is an operator-owned real-data run with the required provenance plus independent corroboration of representative mappings. Until that run exists, the repository has **no established real Anno GUID/name claim** and downstream semantic work must preserve unresolved names rather than inventing them.
