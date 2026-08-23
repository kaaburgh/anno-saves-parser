import json
import unittest
from unittest.mock import patch

import anno_save_probe as probe
import canonical_sort


class CanonicalSessionSortOracleTests(unittest.TestCase):
    @staticmethod
    def _raw_session(
        *,
        guid=None,
        session_id=None,
        map_name=None,
        area_id=None,
    ):
        raw = {
            "guid": guid,
            "id": session_id,
            "player_area_ids": [],
            "areas": {},
            "player_buildings": [],
        }
        if map_name is not None:
            raw["map"] = map_name
        if area_id is not None:
            raw["player_area_ids"] = [area_id]
            raw["areas"] = {
                str(area_id): {
                    "owner_id": 0,
                    "city_name_guid": None,
                    "city_name_iterator": None,
                }
            }
        return raw

    @staticmethod
    def _eager_reference_key(session):
        guid = session.get("session_guid")
        session_id = session.get("session_id")
        return (
            guid is None,
            guid if guid is not None else 0,
            session_id is None,
            session_id if session_id is not None else 0,
            session.get("map") or "",
            json.dumps(
                session,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ),
        )

    @staticmethod
    def _project_one(raw):
        return probe.build_canonical_state("fixture.a7s", [raw])["sessions"][0]

    def _assert_matches_eager_reference(self, raw_sessions):
        projected = [self._project_one(raw) for raw in raw_sessions]
        expected = sorted(projected, key=self._eager_reference_key)
        candidate = canonical_sort.sort_canonical_sessions(projected)
        actual = probe.build_canonical_state("fixture.a7s", raw_sessions)["sessions"]
        self.assertEqual(candidate, expected)
        self.assertEqual(actual, expected)
        self.assertEqual(
            json.dumps(candidate, sort_keys=True, separators=(",", ":")),
            json.dumps(expected, sort_keys=True, separators=(",", ":")),
        )

    def test_unique_primary_identities_match_eager_reference(self):
        raw_sessions = [
            self._raw_session(guid=300, session_id=3, map_name="Map C"),
            self._raw_session(guid=100, session_id=1, map_name="Map A"),
            self._raw_session(guid=None, session_id=7, map_name="Map B"),
            self._raw_session(guid=200, session_id=2, map_name="Map B"),
        ]
        self._assert_matches_eager_reference(raw_sessions)
        with patch(
            "canonical_sort._canonical_session_state_tiebreaker",
            wraps=canonical_sort._canonical_session_state_tiebreaker,
        ) as tiebreaker:
            probe.build_canonical_state("fixture.a7s", raw_sessions)
        self.assertEqual(tiebreaker.call_count, 0)

    def test_actual_primary_ties_match_full_state_tiebreaker(self):
        raw_sessions = [
            self._raw_session(
                guid=100,
                session_id=1,
                map_name="Map A",
                area_id=9,
            ),
            self._raw_session(
                guid=100,
                session_id=1,
                map_name="Map A",
                area_id=2,
            ),
            self._raw_session(
                guid=100,
                session_id=1,
                map_name="Map A",
                area_id=5,
            ),
        ]
        self._assert_matches_eager_reference(raw_sessions)
        with patch(
            "canonical_sort._canonical_session_state_tiebreaker",
            wraps=canonical_sort._canonical_session_state_tiebreaker,
        ) as tiebreaker:
            probe.build_canonical_state("fixture.a7s", raw_sessions)
        self.assertEqual(tiebreaker.call_count, 3)

    def test_null_identity_ties_match_full_state_tiebreaker(self):
        self._assert_matches_eager_reference(
            [
                self._raw_session(
                    guid=None,
                    session_id=None,
                    map_name="",
                    area_id=8,
                ),
                self._raw_session(
                    guid=None,
                    session_id=None,
                    map_name="",
                    area_id=3,
                ),
            ]
        )


if __name__ == "__main__":
    unittest.main()
