# Raw structural diff contract

The structural diff compares two canonical state schema v1 documents. It is deliberately pre-semantic: every event describes an observed structural change only and must not be read as a gameplay judgement.

## Object event attribution

Every object-level event in `added`, `removed`, `moved`, `component_changed`, `guid_changed`, and `direction_changed` carries the same canonical session attribution fields: `session_guid`, `session_id`, and optional `map` when that field is present on the canonical session. This preserves the same fallback identity used by structural indexing, so GUID-less sessions remain attributable through their `(session_id, map)` evidence instead of losing context in selected event sections.

GUID/name enrichment follows event content rather than structural-diff section names. Any top-level event dictionary carrying `guid` receives a parallel `guid_name`; `from_guid` and `to_guid` receive `from_guid_name` and `to_guid_name`. Raw numeric GUID fields remain unchanged. Adding another GUID-bearing event section therefore does not require a separate consumer allowlist merely to preserve exact mapping enrichment.

## Player-area lifecycle events

The diff emits two explicit player-area lifecycle sections:

- `area_added` / `area_added_count` when a canonical player area is absent from the previous state and present in the current state;
- `area_removed` / `area_removed_count` for the reverse transition.

Here, "lifecycle" means lifecycle **inside the canonical player-area projection**. Canonical schema v1 keeps only areas observed as player-owned; it does not retain the full set of non-player areas or an ownership-history record. Therefore an absent→present `area_added` event establishes only that the area entered the player-area projection between the two snapshots. It does not by itself distinguish physical area creation from an already-existing area becoming player-owned, parser-recognition changes, or another target-side cause that yields the same canonical transition. `area_removed` has the symmetric limitation.

Area identity is the canonical session diff identity plus `area_id`. A session with `session_guid` uses that GUID. When the GUID is absent, the existing `(session_id, map)` fallback is used; ambiguous or unidentifiable sessions are rejected by the same fail-closed rules used for object diffs.

Each event contains only canonical identity/attribution fields: `session_guid`, `session_id`, optional `map` when present on the canonical session, and `area_id`. The event does not establish ownership-transition cause, physical island/area creation or destruction, settlement, conquest, discovery, or any other gameplay meaning. Consumers that need one of those claims require additional independently supported evidence rather than inferring it from projection membership alone.

Area events are deterministic and sorted by session identity followed by `area_id`.

## Orthogonality to object events

Area lifecycle events do not replace or collapse nested object evidence. If a newly present player-area projection entry also contains new building objects, the diff emits both one `area_added` event and the ordinary per-object `added` events. Likewise, removing an area from the player-area projection does not suppress its object-level `removed` events.

An empty canonical player area can therefore produce an area lifecycle event with zero corresponding object events. Conversely, object additions/removals within an already-present area do not produce an area lifecycle event.

## Evidence boundary

These events are deterministic transformations of canonical state. Synthetic regression fixtures establish the contract and ordering behavior; they do not establish target-specific gameplay semantics or the underlying target-side cause of a player-area projection transition. Private real-save observations may motivate the feature, but proprietary `.a7s` saves and private derived dumps are not committed as fixtures.
