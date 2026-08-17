# Raw structural diff contract

The structural diff compares two canonical state schema v1 documents. It is deliberately pre-semantic: every event describes an observed structural change only and must not be read as a gameplay judgement.

## Player-area lifecycle events

The diff emits two explicit player-area lifecycle sections:

- `area_added` / `area_added_count` when a canonical player area is absent from the previous state and present in the current state;
- `area_removed` / `area_removed_count` for the reverse transition.

Area identity is the canonical session diff identity plus `area_id`. A session with `session_guid` uses that GUID. When the GUID is absent, the existing `(session_id, map)` fallback is used; ambiguous or unidentifiable sessions are rejected by the same fail-closed rules used for object diffs.

Each event contains only canonical identity/attribution fields: `session_guid`, `session_id`, optional `map` when present on the canonical session, and `area_id`. The event does not infer ownership transitions, island claims, settlements, conquest, discovery, or any other gameplay meaning.

Area events are deterministic and sorted by session identity followed by `area_id`.

## Orthogonality to object events

Area lifecycle events do not replace or collapse nested object evidence. If a newly present area also contains new building objects, the diff emits both one `area_added` event and the ordinary per-object `added` events. Likewise, removing an area does not suppress its object-level `removed` events.

An empty canonical player area can therefore produce an area lifecycle event with zero corresponding object events. Conversely, object additions/removals within an already-present area do not produce an area lifecycle event.

## Evidence boundary

These events are deterministic transformations of canonical state. Synthetic regression fixtures establish the contract and ordering behavior; they do not establish target-specific gameplay semantics. Private real-save observations may motivate the feature, but proprietary `.a7s` saves and private derived dumps are not committed as fixtures.
