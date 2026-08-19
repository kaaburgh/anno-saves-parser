import gzip
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from anno_save_probe import extract_rda_member


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI = PROJECT_ROOT / "anno_save_probe.py"

# Fixture-format constants are intentionally independent of production parser
# constants so this regression fails if producer and consumer definitions drift.
FIXTURE_RDA_MAGIC = b"Resource File V2.2"
FIXTURE_BBDOM_V3_MAGIC = bytes.fromhex("08000000fdffffff")
FIXTURE_PAD_BLOCK = 8


def _record_tag(ident):
    return struct.pack("<ii", 0, ident)


def _record_end():
    return struct.pack("<ii", 0, 0)


def _record_attr(ident, value):
    padding = (-len(value)) % FIXTURE_PAD_BLOCK
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
    trailer = struct.pack("<ii", tags_off, attrs_off) + FIXTURE_BBDOM_V3_MAGIC
    return body + tag_dict + attr_dict + trailer


def _session_blob(guid, x):
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
        32772: "Position",
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
        _record_attr(32771, guid.to_bytes(4, "little")),
        _record_attr(32772, struct.pack("<fff", x, 2.0, 3.0)),
        _record_tag(10),
        _record_end(),
        _record_end(),
        _record_end(),
        _record_end(),
        _record_end(),
        _record_end(),
    ]
    return _filedb(records, tags, attrs)


def _top_level_blob(session_blob, entry_tag_name=None):
    tags = {
        2: "MetaGameManager",
        3: "GameSessions",
        4: "SessionDesc",
        5: "SessionData",
    }
    if entry_tag_name is not None:
        tags[1] = entry_tag_name
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


def _meta_blob(timestamp, save_name):
    attrs = {32768: "LastModTime", 32769: "CorporationSaveGameName"}
    records = [
        _record_attr(32768, timestamp.to_bytes(8, "little")),
        _record_attr(32769, save_name.encode("utf-16le") + b"\x00\x00"),
    ]
    return _filedb(records, {}, attrs)


def _rda_member_name(name):
    raw = name.encode("utf-16le")
    if len(raw) > 518:
        raise ValueError("synthetic RDA member name is too long")
    return raw + b"\x00" * (520 - len(raw))


def _rda_archive(members):
    prefix_size = len(FIXTURE_RDA_MAGIC) + 766 + 8
    payload = bytearray()
    entries = []
    for name, data in members:
        offset = prefix_size + len(payload)
        payload.extend(data)
        entries.append(
            _rda_member_name(name)
            + struct.pack("<QQQQQ", offset, len(data), len(data), 0, 0)
        )
    directory = b"".join(entries)
    block_offset = prefix_size + len(payload) + len(directory)
    header = FIXTURE_RDA_MAGIC + (b"\x00" * 766) + struct.pack("<Q", block_offset)
    block = struct.pack("<IIQQQ", 0, len(entries), len(directory), len(directory), 0)
    return header + bytes(payload) + directory + block


def _write_save(path, timestamp, guid, x, entry_tag_name=None):
    meta = zlib.compress(_meta_blob(timestamp, path.stem))
    data = zlib.compress(_top_level_blob(_session_blob(guid, x), entry_tag_name))
    path.write_bytes(_rda_archive([("meta.a7s", meta), ("data.a7s", data)]))


def _run_cli(*args, check=True):
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        cwd=PROJECT_ROOT,
        check=check,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _read_canonical(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


class SyntheticEndToEndTests(unittest.TestCase):
    def _make_pair(self, root):
        first = root / "Autosave 001.a7s"
        second = root / "Autosave 002.a7s"
        _write_save(first, 1_700_000_000, 777001, 10.0)
        _write_save(second, 1_700_000_060, 777002, 11.0)
        return first, second

    def test_list_uses_internal_metadata_order(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first, second = self._make_pair(root)
            first.touch()
            second.touch()
            # Reverse filesystem mtimes so passing this test requires LastModTime.
            first_mtime = 1_800_000_060
            second_mtime = 1_800_000_000
            first.touch()
            second.touch()
            import os
            os.utime(first, (first_mtime, first_mtime))
            os.utime(second, (second_mtime, second_mtime))

            result = _run_cli(root, "--list")

        self.assertIn("[internal]", result.stdout)
        self.assertLess(result.stdout.index(first.name), result.stdout.index(second.name))

    def test_real_serial_and_process_pool_cli_outputs_match(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make_pair(root)
            serial_out = root / "serial"
            parallel_out = root / "parallel"

            serial = _run_cli(root, "-o", serial_out)
            parallel = _run_cli(root, "--workers", "2", "-o", parallel_out)

            serial_summary = json.loads((serial_out / "summary.json").read_text(encoding="utf-8"))
            parallel_summary = json.loads((parallel_out / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(serial_summary, parallel_summary)
            self.assertIn("mode=serial", serial.stdout)
            self.assertIn("active=2 mode=process", parallel.stdout)

            names = ["Autosave_001.canonical.json.gz", "Autosave_002.canonical.json.gz"]
            for name in names:
                self.assertEqual(
                    _read_canonical(serial_out / name),
                    _read_canonical(parallel_out / name),
                )

        self.assertEqual(len(serial_summary["states"]), 2)
        self.assertEqual(len(serial_summary["diffs"]), 1)
        diff = serial_summary["diffs"][0]
        self.assertEqual(diff["moved_count"], 1)
        self.assertEqual(diff["guid_changed_count"], 1)

    def test_cli_rejects_save_with_no_recognized_sessions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save = root / "Unrecognized.a7s"
            output = root / "out"
            _write_save(
                save,
                1_700_000_000,
                777001,
                10.0,
                entry_tag_name="Entry",
            )

            result = _run_cli(save, "-o", output, check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "no GameSession descriptors recognized",
                result.stdout + result.stderr,
            )
            self.assertFalse((output / "Unrecognized.canonical.json.gz").exists())
            self.assertFalse((output / "summary.json").exists())

    def test_extract_rda_member_rejects_missing_or_duplicate_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            missing = root / "MissingMember.a7s"
            missing.write_bytes(_rda_archive([("other.bin", b"x")]))
            duplicate = root / "DuplicateMember.a7s"
            duplicate.write_bytes(
                _rda_archive([("meta.a7s", b"first"), ("meta.a7s", b"second")])
            )

            with self.assertRaisesRegex(
                ValueError,
                "required RDA member 'meta.a7s' not found",
            ):
                extract_rda_member(missing, "meta.a7s")
            with self.assertRaisesRegex(
                ValueError,
                "required RDA member 'meta.a7s' is ambiguous: found 2 entries",
            ):
                extract_rda_member(duplicate, "meta.a7s")

    def test_cli_rejects_missing_or_duplicate_data_member(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            meta = zlib.compress(_meta_blob(1_700_000_000, "RequiredData"))
            data = zlib.compress(_top_level_blob(_session_blob(777001, 10.0)))

            missing = root / "MissingData.a7s"
            missing.write_bytes(_rda_archive([("meta.a7s", meta)]))
            missing_out = root / "missing-out"
            missing_result = _run_cli(missing, "-o", missing_out, check=False)

            self.assertNotEqual(missing_result.returncode, 0)
            self.assertIn(
                "required RDA member 'data.a7s' not found",
                missing_result.stdout + missing_result.stderr,
            )
            self.assertFalse((missing_out / "MissingData.canonical.json.gz").exists())
            self.assertFalse((missing_out / "summary.json").exists())

            duplicate = root / "DuplicateData.a7s"
            duplicate.write_bytes(
                _rda_archive(
                    [("meta.a7s", meta), ("data.a7s", data), ("data.a7s", data)]
                )
            )
            duplicate_out = root / "duplicate-out"
            duplicate_result = _run_cli(duplicate, "-o", duplicate_out, check=False)

            self.assertNotEqual(duplicate_result.returncode, 0)
            self.assertIn(
                "required RDA member 'data.a7s' is ambiguous: found 2 entries",
                duplicate_result.stdout + duplicate_result.stderr,
            )
            self.assertFalse((duplicate_out / "DuplicateData.canonical.json.gz").exists())
            self.assertFalse((duplicate_out / "summary.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
