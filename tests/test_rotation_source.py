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


def _session_blob(*, rotation=None, rotation90=None):
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
    }
    attrs = {
        32768: "id",
        32769: "AreaID",
        32770: "ID",
        32771: "guid",
        32772: "Rotation",
        32773: "Rotation90",
    }
    records = [
        _record_tag(2),
        _record_tag(3),
        _record_tag(1),
        _record_tag(4),
        _record_attr(32768, (0).to_bytes(4, "little")),
        _record_end(),
        _record_tag(5),
        _record_attr(32769, (42).to_bytes(4, "little")),
        _record_end(),
        _record_end(),
        _record_end(),
        _record_tag(6),
        _record_tag(7),
        _record_tag(8),
        _record_tag(9),
        _record_tag(1),
        _record_attr(32770, (9001).to_bytes(8, "little")),
        _record_attr(32771, (777001).to_bytes(4, "little")),
    ]
    if rotation is not None:
        records.append(_record_attr(32772, rotation.to_bytes(4, "little")))
    if rotation90 is not None:
        records.append(_record_attr(32773, rotation90.to_bytes(4, "little")))
    records.extend(
        [
            _record_tag(10),
            _record_end(),
            _record_end(),
            _record_end(),
            _record_end(),
            _record_end(),
            _record_end(),
            _record_end(),
        ]
    )
    return _filedb(records, tags, attrs)


class RotationSourceTests(unittest.TestCase):
    def _parse(self, **kwargs):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "fixture.bin"
        path.write_bytes(_session_blob(**kwargs))
        return probe.parse_session(path)

    def _canonical_building(self, **kwargs):
        parsed = self._parse(**kwargs)
        state = probe.build_canonical_state(
            "fixture.a7s",
            [{"guid": 123456, "id": 7, "map": "synthetic/map.a7t", **parsed}],
        )
        return state["sessions"][0]["buildings"][0]

    def test_rotation_preserves_source(self):
        building = self._canonical_building(rotation=17)
        self.assertEqual(building["rotation"], 17)
        self.assertEqual(building["rotation_source"], "Rotation")

    def test_rotation90_preserves_source(self):
        building = self._canonical_building(rotation90=23)
        self.assertEqual(building["rotation"], 23)
        self.assertEqual(building["rotation_source"], "Rotation90")

    def test_rotation_and_rotation90_together_fail_closed(self):
        with self.assertRaisesRegex(
            ValueError,
            r"both Rotation and Rotation90 attributes",
        ):
            self._parse(rotation=17, rotation90=23)


if __name__ == "__main__":
    unittest.main(verbosity=2)
