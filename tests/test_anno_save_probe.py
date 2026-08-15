import contextlib
import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import anno_save_probe as probe


class CliContractTests(unittest.TestCase):
    def test_real_world_command_line_is_accepted(self):
        args = probe.parse_cli_args([
            r"C:\Users\gamer\Documents\Anno 1800\accounts\id\Valentine McStay",
            "--from", "Autosave 711",
            "--limit", "3",
            "-o", "711_l3_2",
        ])
        self.assertEqual(args.start, "Autosave 711")
        self.assertEqual(args.limit, 3)
        self.assertEqual(args.output, Path("711_l3_2"))
        self.assertEqual(len(args.inputs), 1)

    def test_date_start_is_accepted(self):
        args = probe.parse_cli_args([r"C:\saves", "--from", "2026-08-15"])
        self.assertEqual(args.start, "2026-08-15")

    def test_list_flag_is_accepted(self):
        args = probe.parse_cli_args([r"C:\saves", "--list"])
        self.assertTrue(args.list)

    def test_help_mentions_public_options(self):
        help_text = probe.build_arg_parser().format_help()
        for option in ("--from", "--limit", "--list", "--output", "--version"):
            self.assertIn(option, help_text)

    def test_version_is_exposed(self):
        self.assertEqual(probe.__version__, "0.2.0")


class SelectionTests(unittest.TestCase):
    def setUp(self):
        probe.SAVE_META_CACHE.clear()

    def test_select_from_exact_name_without_extension(self):
        saves = [Path("Autosave 710.a7s"), Path("Autosave 711.a7s"), Path("Autosave 712.a7s")]
        self.assertEqual(probe.select_from(saves, "Autosave 711"), saves[1:])

    def test_select_from_date_uses_internal_timestamp(self):
        saves = [Path("Autosave 710.a7s"), Path("Autosave 711.a7s"), Path("Autosave 712.a7s")]
        ts = {
            "Autosave 710.a7s": datetime(2026, 8, 14, 23, 55).timestamp(),
            "Autosave 711.a7s": datetime(2026, 8, 15, 0, 0).timestamp(),
            "Autosave 712.a7s": datetime(2026, 8, 15, 0, 5).timestamp(),
        }
        with patch.object(probe, "cached_save_meta", side_effect=lambda p: {"last_mod_time": ts[p.name]}):
            self.assertEqual(probe.select_from(saves, "2026-08-15"), saves[1:])

    def test_discover_sorts_using_internal_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("Autosave 713.a7s", "Autosave 711.a7s", "Autosave 712.a7s"):
                (root / name).write_bytes(b"fixture")
            ts = {
                "Autosave 711.a7s": 100,
                "Autosave 712.a7s": 200,
                "Autosave 713.a7s": 300,
            }
            with patch.object(probe, "cached_save_meta", side_effect=lambda p: {"last_mod_time": ts[p.name]}):
                found = probe.discover_saves([root])
            self.assertEqual([p.name for p in found], ["Autosave 711.a7s", "Autosave 712.a7s", "Autosave 713.a7s"])


class ProgressTests(unittest.TestCase):
    def test_say_flushes_immediately(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            progress = probe.Progress(interval=1.0)
            progress.say("[start] hello")
        self.assertIn("[start] hello", stream.getvalue())

    def test_heartbeat_emits_after_interval(self):
        stream = io.StringIO()
        with patch.object(probe.time, "monotonic", side_effect=[10.0, 10.2, 11.1]):
            with contextlib.redirect_stdout(stream):
                progress = probe.Progress(interval=1.0)
                progress.say("start")
                progress.maybe("too soon")
                progress.maybe("heartbeat")
        text = stream.getvalue()
        self.assertNotIn("too soon", text)
        self.assertIn("heartbeat", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
