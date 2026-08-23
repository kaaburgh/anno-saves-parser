import struct
import tempfile
import unittest
from pathlib import Path

from anno_save_probe import (
    BBDOM_V3_MAGIC,
    _decode_utf16,
    _entry_tag_ids,
    _ids_named,
    _padded,
    _read_attr,
    _u32,
    bb_meta,
    extract_sessions,
)
from top_level_session_scan import scan_top_level_sessions_mmap


PAD_BLOCK = 8


def _record_tag(ident):
    return struct.pack("<ii", 0, ident)


def _record_end():
    return struct.pack("<ii", 0, 0)


def _record_attr(ident, value):
    padding = (-len(value)) % PAD_BLOCK
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
    trailer = struct.pack("<ii", tags_off, attrs_off) + BBDOM_V3_MAGIC
    return body + tag_dict + attr_dict + trailer


def _fixture_two_sessions():
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
    records = [_record_tag(2), _record_tag(3)]
    for guid, session_id, map_name, payload in (
        (123456, 7, "synthetic/a.a7t", b"A" * 17),
        (654321, 9, "synthetic/b.a7t", b"B" * 9),
    ):
        records.extend(
            [
                _record_tag(1),
                _record_tag(4),
                _record_attr(32768, guid.to_bytes(4, "little")),
                _record_attr(32769, session_id.to_bytes(4, "little")),
                _record_attr(32770, map_name.encode("utf-16le") + b"\x00\x00"),
                _record_end(),
                _record_tag(5),
                _record_attr(32771, payload),
                _record_end(),
                _record_end(),
            ]
        )
    records.extend([_record_end(), _record_end()])
    return _filedb(records, tags, attrs)


def _fixture_bad_binary_header(size):
    tags = {
        2: "MetaGameManager",
        3: "GameSessions",
        4: "SessionData",
    }
    attrs = {32771: "BinaryData"}
    records = [
        _record_tag(2),
        _record_tag(3),
        _record_tag(1),
        _record_tag(4),
        struct.pack("<ii", size, 32771),
    ]
    if size > 0:
        records.append(b"x" * min(size, 4))
    return _filedb(records, tags, attrs)


def _reference_extract_sessions(path):
    """Buffered reference scanner retained only as a differential test oracle."""
    tags_off, _, tags, attrs = bb_meta(path)
    entry_ids = _entry_tag_ids(tags)
    game_sessions_ids = _ids_named(tags, "GameSessions")
    session_data_ids = _ids_named(tags, "SessionData")
    session_desc_ids = _ids_named(tags, "SessionDesc")
    binary_data_ids = _ids_named(attrs, "BinaryData")
    session_guid_ids = _ids_named(attrs, "SessionGUID")
    session_id_ids = _ids_named(attrs, "SessionID")
    session_map_ids = _ids_named(attrs, "SessionMap")

    sessions = []
    stack = []
    current = None
    index = -1

    with path.open("rb") as stream:
        pos = 0
        while pos < tags_off:
            header = stream.read(8)
            if len(header) != 8:
                raise EOFError("top-level FileDB record header truncated")
            size, raw_id = struct.unpack("<ii", header)
            pos += 8

            ident = raw_id & 0xFFFF
            if ident == 0:
                if stack:
                    popped = stack.pop()
                    if (
                        popped in entry_ids
                        and stack
                        and stack[-1] in game_sessions_ids
                        and current is not None
                    ):
                        sessions.append(current)
                        current = None
                continue

            if ident < 32768:
                stack.append(ident)
                if (
                    ident in entry_ids
                    and len(stack) >= 2
                    and stack[-2] in game_sessions_ids
                ):
                    index += 1
                    current = {"index": index}
                continue

            if size < 0:
                raise ValueError("negative top-level FileDB attribute size")
            padded = _padded(size)
            value_offset = stream.tell()
            if value_offset + padded > tags_off:
                raise EOFError("top-level FileDB attribute payload truncated")

            is_session_blob = (
                ident in binary_data_ids
                and len(stack) >= 3
                and stack[-1] in session_data_ids
                and stack[-2] in entry_ids
                and stack[-3] in game_sessions_ids
            )
            if is_session_blob:
                if current is not None:
                    current["binary_offset"] = value_offset
                    current["binary_size"] = size
                stream.seek(padded, 1)
                pos += padded
                continue

            descriptor_attr = (
                current is not None
                and len(stack) >= 4
                and stack[-1] in session_desc_ids
                and stack[-2] in entry_ids
                and (
                    ident in session_guid_ids
                    or ident in session_id_ids
                    or ident in session_map_ids
                )
            )
            if descriptor_attr:
                raw = _read_attr(stream, size)
                if ident in session_guid_ids:
                    current["guid"] = _u32(raw, "SessionGUID")
                elif ident in session_id_ids:
                    current["id"] = _u32(raw, "SessionID")
                elif ident in session_map_ids:
                    current["map"] = _decode_utf16(raw)
            else:
                stream.seek(padded, 1)
            pos += padded

    for session in sessions:
        if "binary_offset" not in session or "binary_size" not in session:
            raise ValueError("GameSession descriptor is missing BinaryData")
    return sessions


def _mmap_candidate(path):
    tags_off, _, tags, attrs = bb_meta(path)
    return scan_top_level_sessions_mmap(path, tags_off, tags, attrs)


class TopLevelSessionScannerOracleTests(unittest.TestCase):
    def _write_fixture(self, root, data):
        path = root / "data.bin"
        path.write_bytes(data)
        return path

    def _assert_same_failure(self, path, expected_type):
        with self.assertRaises(expected_type) as reference:
            _reference_extract_sessions(path)
        with self.assertRaises(expected_type) as production:
            extract_sessions(path)
        with self.assertRaises(expected_type) as candidate:
            _mmap_candidate(path)
        self.assertEqual(str(production.exception), str(reference.exception))
        self.assertEqual(str(candidate.exception), str(reference.exception))

    def test_reference_production_and_mmap_descriptors_match_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._write_fixture(Path(td), _fixture_two_sessions())
            reference = _reference_extract_sessions(path)
            production = extract_sessions(path)
            candidate = _mmap_candidate(path)

        self.assertEqual(production, reference)
        self.assertEqual(candidate, reference)
        self.assertEqual(
            [
                (item["guid"], item["id"], item["map"], item["binary_size"])
                for item in candidate
            ],
            [
                (123456, 7, "synthetic/a.a7t", 17),
                (654321, 9, "synthetic/b.a7t", 9),
            ],
        )
        self.assertLess(candidate[0]["binary_offset"], candidate[1]["binary_offset"])

    def test_negative_attribute_size_matches_reference_failure(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._write_fixture(Path(td), _fixture_bad_binary_header(-1))
            self._assert_same_failure(path, ValueError)

    def test_truncated_attribute_payload_matches_reference_failure(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._write_fixture(Path(td), _fixture_bad_binary_header(32))
            self._assert_same_failure(path, EOFError)


if __name__ == "__main__":
    unittest.main()
