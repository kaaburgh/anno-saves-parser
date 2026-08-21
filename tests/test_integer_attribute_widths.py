import struct
import tempfile
import unittest
from pathlib import Path

import anno_save_probe as probe


def _record_tag(ident):
    return struct.pack("<ii", 0, ident)


def _record_end():
    return struct.pack("<ii", 0, 0)


def _record_attr(ident, value):
    padding = (-len(value)) % probe.PAD_BLOCK
    return struct.pack("<ii", len(value), ident) + value + (b"\x00" * padding)


def _dictionary(entries):
    ordered = sorted(entries.items())
    ids = b"".join(struct.pack("<H", ident) for ident, _ in ordered)
    names = b"".join(name.encode("utf-8") + b"\x00" for _, name in ordered)
    return struct.pack("<i", len(ordered)) + ids + names


def _filedb(records, tags, attrs):
    body = b"".join(records)
    tags_off = len(body)
    tag_dict = _dictionary(tags)
    attrs_off = tags_off + len(tag_dict)
    attr_dict = _dictionary(attrs)
    trailer = struct.pack("<ii", tags_off, attrs_off) + probe.BBDOM_V3_MAGIC
    return body + tag_dict + attr_dict + trailer


def _session_blob(
    *,
    owner_raw=None,
    guid_raw=None,
    area_manager_id=42,
    area_id=42,
    entry_tag_name=None,
):
    if owner_raw is None:
        owner_raw = (0).to_bytes(4, "little")
    if guid_raw is None:
        guid_raw = (777001).to_bytes(4, "little")
    tags = {
        2: "GameSessionManager",
        3: "AreaInfo",
        4: "Owner",
        5: "PassiveTrade",
        6: f"AreaManager_{area_manager_id}",
        7: "AreaObjectManager",
        8: "GameObject",
        9: "objects",
        10: "Building",
    }
    if entry_tag_name is not None:
        tags[1] = entry_tag_name
    attrs = {
        32768: "id",
        32769: "AreaID",
        32770: "ID",
        32771: "guid",
    }
    records = [
        _record_tag(2),
        _record_tag(3),
        _record_tag(1),
        _record_tag(4),
        _record_attr(32768, owner_raw),
        _record_end(),
        _record_tag(5),
        _record_attr(32769, area_id.to_bytes(4, "little")),
        _record_end(),
        _record_end(),
        _record_end(),
        _record_tag(6),
        _record_tag(7),
        _record_tag(8),
        _record_tag(9),
        _record_tag(1),
        _record_attr(32770, (9001).to_bytes(8, "little")),
        _record_attr(32771, guid_raw),
        _record_tag(10),
        _record_end(),
        _record_end(),
        _record_end(),
        _record_end(),
        _record_end(),
        _record_end(),
        _record_end(),
    ]
    return _filedb(records, tags, attrs)


def _top_level_blob(*, session_guid_raw=None, session_id_raw=None):
    if session_guid_raw is None:
        session_guid_raw = (123456).to_bytes(4, "little")
    if session_id_raw is None:
        session_id_raw = (7).to_bytes(4, "little")
    session_blob = _session_blob()
    tags = {
        2: "MetaGameManager",
        3: "GameSessions",
        4: "SessionDesc",
        5: "SessionData",
    }
    attrs = {
        32768: "SessionGUID",
        32769: "SessionID",
        32770: "SessionMap",
        32771: "BinaryData",
    }
    records = [
        _record_tag(2),
        _record_tag(3),
        _record_tag(1),
        _record_tag(4),
        _record_attr(32768, session_guid_raw),
        _record_attr(32769, session_id_raw),
        _record_attr(32770, "synthetic/map.a7t".encode("utf-16le") + b"\x00\x00"),
        _record_end(),
        _record_tag(5),
        _record_attr(32771, session_blob),
        _record_end(),
        _record_end(),
        _record_end(),
        _record_end(),
    ]
    return _filedb(records, tags, attrs)


class IntegerAttributeWidthTests(unittest.TestCase):
    def _write_blob(self, raw):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "fixture.bin"
        path.write_bytes(raw)
        return path

    def test_zero_length_owner_id_is_rejected_before_player_ownership(self):
        path = self._write_blob(_session_blob(owner_raw=b""))
        with self.assertRaisesRegex(ValueError, r"Owner/id must be exactly 4 bytes; got 0"):
            probe.parse_session(path)

    def test_oversized_object_guid_is_rejected_before_canonical_state(self):
        path = self._write_blob(_session_blob(guid_raw=(1 << 40 | 7).to_bytes(8, "little")))
        with self.assertRaisesRegex(ValueError, r"guid must be exactly 4 bytes; got 8"):
            probe.parse_session(path)

    def test_oversized_session_guid_is_rejected_in_descriptor_scan(self):
        path = self._write_blob(
            _top_level_blob(session_guid_raw=(1 << 40 | 7).to_bytes(8, "little"))
        )
        with self.assertRaisesRegex(ValueError, r"SessionGUID must be exactly 4 bytes; got 8"):
            probe.extract_sessions(path)

    def test_valid_fixed_width_fields_keep_variable_width_object_id(self):
        path = self._write_blob(_session_blob())
        parsed = probe.parse_session(path)
        self.assertEqual(parsed["player_area_ids"], [42])
        self.assertEqual(parsed["player_buildings"][0]["id"], 9001)
        self.assertEqual(parsed["player_buildings"][0]["guid"], 777001)

    def test_non_player_owner_is_preserved_as_observed_area_state(self):
        path = self._write_blob(
            _session_blob(owner_raw=(3).to_bytes(4, "little"))
        )
        parsed = probe.parse_session(path)
        self.assertEqual(parsed["player_area_ids"], [])
        self.assertEqual(parsed["observed_areas"], [{"area_id": 42, "owner_id": 3}])

    def test_disjoint_player_area_and_area_manager_namespaces_fail_closed(self):
        path = self._write_blob(_session_blob(area_manager_id=42, area_id=99))
        with self.assertRaisesRegex(
            ValueError,
            r"player AreaID and AreaManager identities are disjoint",
        ):
            probe.parse_session(path)

    def test_unrecognized_area_info_entry_vocabulary_fails_closed(self):
        path = self._write_blob(_session_blob(entry_tag_name="Entry"))
        with self.assertRaisesRegex(
            ValueError,
            r"AreaInfo container has direct child tag records but no recognized entries",
        ):
            probe.parse_session(path)

    def test_session_without_area_info_container_remains_valid(self):
        path = self._write_blob(
            _filedb(
                [_record_tag(2), _record_end()],
                {2: "GameSessionManager"},
                {},
            )
        )
        parsed = probe.parse_session(path)
        self.assertEqual(parsed["player_area_ids"], [])
        self.assertEqual(parsed["observed_areas"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
