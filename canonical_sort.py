#!/usr/bin/env python3
"""Internal helpers for deterministic canonical session ordering."""
from __future__ import annotations

import json


def _canonical_session_primary_sort_key(session: dict) -> tuple:
    """Return the inexpensive identity portion of canonical session ordering."""
    guid = session.get("session_guid")
    session_id = session.get("session_id")
    return (
        guid is None,
        guid if guid is not None else 0,
        session_id is None,
        session_id if session_id is not None else 0,
        session.get("map") or "",
    )


def _canonical_session_state_tiebreaker(session: dict) -> str:
    """Return the existing deterministic full-state tie-breaker."""
    return json.dumps(
        session,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sort_canonical_sessions(sessions: list[dict]) -> list[dict]:
    """Sort sessions while serializing full state only for real identity ties."""
    ordered = sorted(sessions, key=_canonical_session_primary_sort_key)
    result: list[dict] = []
    index = 0
    while index < len(ordered):
        primary = _canonical_session_primary_sort_key(ordered[index])
        end = index + 1
        while (
            end < len(ordered)
            and _canonical_session_primary_sort_key(ordered[end]) == primary
        ):
            end += 1

        group = ordered[index:end]
        if len(group) > 1:
            group = sorted(group, key=_canonical_session_state_tiebreaker)
        result.extend(group)
        index = end
    return result
