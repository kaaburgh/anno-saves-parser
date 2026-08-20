# GUID source selection

This document records the source/acquisition decision for real Anno 1800 GUID/name evidence under `ASP-P1-2`. It complements the mapping format and consumer contract in [`guid-mapping.md`](./guid-mapping.md); it does not establish any particular GUID/name pair by itself.

## Decision

Use an operator-controlled Anno 1800 installation as the primary source of real GUID/name evidence. Extract and normalize the relevant asset/localization data locally with a pinned `anno-mods/asset-extractor` release or commit. Do not add extracted game catalogs to this repository merely to populate names.

As of this investigation, `anno-mods/asset-extractor` release `3.0` is the published release inspected. Its documentation states that it extracts from the configured local game installation, parses Anno 1800 `assets.xml`, resolves asset structure, and supports localization. The extractor code is MIT-licensed. Those facts make it a suitable reproducible acquisition/normalization tool, while the game files and extracted data remain separate operator inputs.

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
2. SHA-256 identities for every extracted asset/localization input that materially affects GUID/name interpretation, recorded under stable logical labels;
3. exact `anno-mods/asset-extractor` release or commit identity and, when practical, the acquired artifact digest;
4. exact converter/export implementation identity and, when practical, its artifact digest;
5. the mapping schema/version plus the generated `mapping_content_hash` enforced by `guid_mapping.py`.

Mapping schema v1 carries (2)–(4) directly as optional structured `input_hashes`, `extractor`, and `converter` fields. Those recognized fields are preserved in derived output and participate in `mapping_content_hash`; unknown provenance fields fail closed instead of disappearing silently. Existing schema-v1 mappings without the structured fields remain readable for compatibility, but a new real-target evidence run should populate the structured fields above.

The repository should consume only the resulting small provenance-aware mapping document when the operator is entitled to retain/share it. Raw RDA content, extracted game XML/catalogs, saves, and unrelated extracted assets stay outside the repository.

## Bounded exporter

`guid_mapping_export.py` is an optional operator-side adapter. The normal save parser never imports `assetextractor`; the third-party package is loaded only when this exporter is invoked explicitly against a pinned checkout whose environment is already installed.

The adapter reads the resolved `AssetCache`, uses the requested localized text when present, falls back only to the extractor's own stable asset name, skips assets for which neither exists, sorts output by numeric GUID, and fails closed on invalid GUIDs, conflicting duplicate GUID/name pairs, malformed provenance, or an empty result. It does not infer a nearby or likely name.

Before running it, identify every extracted asset/localization input material to GUID/name interpretation and hash each one with SHA-256. Use stable logical labels such as `assets` or `localization-en` in the mapping. A separate operator-local manifest may record path-to-label details when useful, and the legacy `source_hash` can retain a digest of that manifest for compatibility, but it no longer substitutes for the per-input structured hashes required for a new real evidence run.

Choose an output path separate from the pinned extractor checkout and all source paths in its config. The exporter rejects an output that overwrites the config itself or falls within the configured `game_path`, `cache_path`, or `assetbrowser_dir`, and it also protects the extractor checkout. After the mapping document is fully built and validated, it is published through an atomic same-directory replacement so an interrupted write cannot leave a partial mapping at the requested path.

Example, from an environment where the pinned extractor checkout has already completed its documented extraction/setup:

```text
python guid_mapping_export.py \
  --asset-extractor-root C:/tools/asset-extractor \
  --config C:/tools/asset-extractor/config.json \
  --output C:/anno-evidence/guid-mapping.json \
  --language english \
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

The structured producer/input flags are optional at the schema/CLI compatibility boundary, but extractor identity, converter identity, and material per-input hashes are required evidence for the planned real-target run. Artifact hashes remain required only when practical, matching the evidence policy above.

The output is mapping schema v1 and can be passed to the batch parser with `--guid-mapping`. The export command itself does not establish a real target claim; that requires executing it on the operator-controlled installation, preserving the stated provenance, and independently checking representative GUID/name pairs or another relationship that does not reuse the same derivation.

## Evidence preflight manifest

After the real export, run the dependency-free preflight against the exact mapping file that may be returned for review:

```text
python guid_mapping_evidence.py \
  --mapping C:/anno-evidence/guid-mapping.json \
  --output C:/anno-evidence/guid-mapping-evidence.json
```

The preflight validates the exact bytes it hashes and fails closed unless the mapping contains structured `extractor`, `converter`, and non-empty `input_hashes` provenance. It emits a compact schema-versioned manifest containing the mapping file SHA-256, `mapping_content_hash`, entry count, source/build identity, producer identities, and material input hashes. It deliberately omits all GUID/name entries, so the manifest can be reviewed as provenance metadata without redistributing the extracted catalog.

The manifest records independent corroboration as `required-not-recorded`. That is intentional: the preflight proves that the returned mapping is self-consistent with the repository's provenance contract, not that its names are independently correct. Representative GUID/name checks must still be performed against an independently derived reference or observation and reported separately before `ASP-P1-2` can be treated as target-validated.

The preflight refuses to overwrite the mapping itself and publishes its manifest with an atomic same-directory replacement. A legacy schema-v1 mapping without structured producer/input fields remains valid for the ordinary mapping consumer but is ineligible for this real-evidence preflight.

## Independent corroboration record

After selecting representative GUID/name pairs from a reference that is independent of the exporter derivation, record those observations in a small local JSON document. Do not generate the expected names by reading them back from `guid-mapping.json`; that would only test internal consistency.

Observation schema v1 is intentionally small and strict:

```json
{
  "schema": "anno-saves-parser/guid-mapping-corroboration-observations",
  "schema_version": 1,
  "reference": {
    "identity": "<independent reference identity>",
    "version": "<reference snapshot/version>",
    "artifact_hash": "sha256:<optional pinned reference artifact digest>"
  },
  "checks": [
    {
      "guid": 123456,
      "name": "<independently observed exact name>",
      "locator": "<optional reference locator>"
    }
  ]
}
```

Then bind those observations to the exact exported mapping:

```text
python guid_mapping_corroboration.py \
  --mapping C:/anno-evidence/guid-mapping.json \
  --observations C:/anno-evidence/guid-mapping-observations.json \
  --output C:/anno-evidence/guid-mapping-corroboration.json
```

The verifier uses exact GUID and exact name equality only. Missing GUIDs, mismatched names, duplicate GUID checks, malformed/unknown observation fields, or ambiguous input/output aliasing fail closed. The output binds the exact mapping-file SHA-256 and `mapping_content_hash` to the exact observations-file SHA-256, preserves reference provenance, and includes only the representative checked pairs rather than the full mapping. It is published through an atomic same-directory replacement.

The tool cannot prove that the supplied reference is genuinely independent: the output therefore records `operator-asserted-independent-reference` rather than claiming independence as an automatically established fact. Reviewers must inspect the recorded reference provenance and decide whether it is actually independent of the primary exporter/source path. A source that reuses the same extracted catalog or transformation does not satisfy the evidence requirement merely because this command reports matching names.

## One-shot target-evidence runner

`guid_mapping_target_run.py` is the preferred operator entry point once an independently prepared observations document already exists. It invokes the exporter, provenance preflight, and corroboration CLIs in order with the same Python interpreter and repository checkout, bounds every child stage with `--stage-timeout-seconds` (default 1800 seconds), and stops immediately on a non-zero exit or timeout.

The output directory uses fixed names: `guid-mapping.json`, `guid-mapping-evidence.json`, `guid-mapping-corroboration.json`, and `guid-mapping-target-run.json`. The run record contains only schema/version, the explicit runner identity, safe Python/platform facts, SHA-256 identities for the config and observations inputs, per-stage termination status, and names/digests of produced artifacts. It does not embed the mapping payload, extracted assets, config paths, or observations paths.

The exporter remains the authority for proving that the output directory is outside the immutable extractor/game/cache trees. Therefore the harness writes no run record if the export stage fails before output safety has been established. Once export succeeds, later failures produce a failure run record and no later stage is executed.

Example:

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

The observations document must still come from an independently acceptable reference. The one-shot runner automates sequencing and evidence packaging only; it does not acquire the independent observations, prove their independence, or turn synthetic/CI coverage into target evidence. The three individual CLIs remain supported for debugging and recovery.

## Follow-up boundary

Source selection, a deterministic converter/export seam, machine-checkable producer/input provenance, a safe provenance-preflight manifest, a machine-readable representative-corroboration record, and a bounded one-shot orchestration harness are now prepared, but `ASP-P1-2` is not complete. The remaining evidence step is the operator-owned real-data run itself: prepare independently derived representative observations, run the one-shot harness against the exact installation, and return a successful run record plus the permitted mapping/evidence artifacts whose reference provenance is independently acceptable. Until that run exists, the repository has no established real Anno GUID/name claim and downstream semantic work must preserve unresolved names rather than inventing them.
