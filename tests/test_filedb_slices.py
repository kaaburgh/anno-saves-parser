import io
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


def _session_blob():
    tags = {
        2: "GameSessionManager",
        3: "AreaInfo",
        4: "Owner",
        5: "PassiveTrade",
        6: "AreaManager_42",
        7: "AreaObjectManager",
        8: "GameObject",
        9: "objects",
        10: "Building",
        11: "Warehouse",
    }
    attrs = {
        32768: "CityNameGuid",
        32769: "CityNameIterator",
        32770: "id",
        32771: "AreaID",
        32772: "ID",
        32773: "guid",
        32774: "Position",
        32775: "Direction",
    }
    records = [
        _record_tag(2),
        _record_tag(3),
        _record_tag(1),  # absent from dictionary => legacy parser name '#1'
        _record_attr(32768, (1001).to_bytes(4, "little")),
        _record_attr(32769, (2).to_bytes(4, "little")),
        _record_tag(4),
        _record_attr(32770, (0).to_bytes(4, "little")),
        _record_end(),
        _record_tag(5),
        _record_attr(32771, (42).to_bytes(4, "little")),
        _record_end(),
        _record_end(),
        _record_end(),
        _record_tag(6),
        _record_tag(7),
        _record_tag(8),
        _record_tag(9),
        _record_tag(1),
        _record_attr(32772, (9001).to_bytes(8, "little")),
        _record_attr(32773, (777001).to_bytes(4, "little")),
        _record_attr(32774, struct.pack("<fff", 10.5, 2.25, 30.75)),
        _record_attr(32775, struct.pack("<f", 1.5)),
        _record_tag(10),
        _record_end(),
        _record_tag(11),
        _record_end(),
        _record_end(),
        _record_end(),
        _record_end(),
        _record_end(),
        _record_end(),
    ]
    return _filedb(records, tags, attrs)


def _top_level_blob(session_blob):
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
        _record_attr(32768, (123456).to_bytes(4, "little")),
        _record_attr(32769, (7).to_bytes(4, "little")),
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


class FileDBSliceTests(unittest.TestCase):
    def test_embedded_session_is_located_without_secondary_copy_and_parsed_in_place(self):
        session_blob = _session_blob()
        top_blob = _top_level_blob(session_blob)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            top_path = root / "data.bin"
            top_path.write_bytes(top_blob)
            unused_session_dir = root / "sessions"

            descriptors = probe.extract_sessions(top_path, unused_session_dir)

            self.assertEqual(len(descriptors), 1)
            descriptor = descriptors[0]
            self.assertEqual(descriptor["guid"], 123456)
            self.assertEqual(descriptor["id"], 7)
            self.assertEqual(descriptor["map"], "synthetic/map.a7t")
            self.assertEqual(descriptor["binary_size"], len(session_blob))
            self.assertNotIn("binary_path", descriptor)
            self.assertFalse(unused_session_dir.exists())

            parsed = probe.parse_session(
                top_path,
                base_offset=descriptor["binary_offset"],
                blob_size=descriptor["binary_size"],
            )

        self.assertEqual(parsed["player_area_ids"], [42])
        self.assertEqual(
            parsed["player_buildings"],
            [
                {
                    "area_id": 42,
                    "id": 9001,
                    "guid": 777001,
                    "position": [10.5, 2.25, 30.75],
                    "direction": 1.5,
                    "components": ["Building", "Warehouse"],
                }
            ],
        )

    def test_bounded_slice_matches_standalone_session_parse(self):
        session_blob = _session_blob()
        top_blob = _top_level_blob(session_blob)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            top_path = root / "data.bin"
            session_path = root / "session.bin"
            top_path.write_bytes(top_blob)
            session_path.write_bytes(session_blob)
            descriptor = probe.extract_sessions(top_path)[0]

            embedded = probe.parse_session(
                top_path,
                base_offset=descriptor["binary_offset"],
                blob_size=descriptor["binary_size"],
            )
            standalone = probe.parse_session(session_path)

        self.assertEqual(embedded, standalone)

    def test_slice_bounds_are_rejected_before_mapping(self):
        session_blob = _session_blob()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "session.bin"
            path.write_bytes(session_blob)
            with self.assertRaisesRegex(ValueError, "exceeds source file"):
                probe.parse_session(path, base_offset=1, blob_size=len(session_blob))

    def test_dictionary_string_cannot_cross_slice_boundary(self):
        # One dictionary entry whose name never terminates before the declared slice limit.
        raw = struct.pack("<iH", 1, 7) + b"unterminated"
        with self.assertRaisesRegex(ValueError, "dictionary string exceeds FileDB slice"):
            probe._read_dictionary_at(io.BytesIO(raw), 0, 0, len(raw))

    def test_negative_session_attribute_size_is_rejected(self):
        malformed = _filedb(
            [struct.pack("<ii", -1, 32768)],
            {},
            {32768: "ID"},
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "session.bin"
            path.write_bytes(malformed)
            with self.assertRaisesRegex(ValueError, "negative session FileDB attribute size"):
                probe.parse_session(path)

    def test_negative_top_level_attribute_size_is_rejected(self):
        malformed = _filedb(
            [struct.pack("<ii", -1, 32768)],
            {},
            {32768: "BinaryData"},
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "data.bin"
            path.write_bytes(malformed)
            with self.assertRaisesRegex(ValueError, "negative top-level FileDB attribute size"):
                probe.extract_sessions(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
