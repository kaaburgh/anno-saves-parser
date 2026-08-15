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
        self.assertEqual(probe.__version__, "0.2.1")


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


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


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

    def test_interactive_parse_rewrites_one_live_detail_line(self):
        stream = FakeTTY()
        progress = probe.Progress(stream=stream, interactive=True, terminal_width=120)

        progress.begin_parse("[parse 6/55] Autosave 669.a7s")
        progress.say("  [rda] reading archive directory (10.28 MiB)")
        progress.say("  [data] ready: 267.4 MiB FileDB state")
        progress.finish_parse(
            "[parse 6/55] done in 6.3s: sessions=5 player_buildings=36,030"
        )

        text = stream.getvalue()
        self.assertTrue(text.startswith("[parse 6/55] Autosave 669.a7s\n"))
        self.assertIn(
            probe.Progress.CLEAR_LINE + "  [rda] reading archive directory (10.28 MiB)",
            text,
        )
        self.assertIn(
            probe.Progress.CLEAR_LINE + "  [data] ready: 267.4 MiB FileDB state",
            text,
        )
        self.assertNotIn("\n  [rda]", text)
        self.assertNotIn("\n  [data]", text)
        self.assertTrue(
            text.endswith(
                probe.Progress.CLEAR_LINE
                + probe.Progress.CURSOR_UP
                + probe.Progress.CLEAR_LINE
                + "[parse 6/55] done in 6.3s: sessions=5 player_buildings=36,030\n"
            )
        )

    def test_non_tty_parse_remains_line_oriented_without_ansi(self):
        stream = io.StringIO()
        progress = probe.Progress(stream=stream, interactive=False)

        progress.begin_parse("[parse 1/2] Autosave 711.a7s")
        progress.say("  [data] reading + decompressing data.a7s")
        progress.finish_parse("[parse 1/2] done in 5.6s: sessions=5 player_buildings=37,570")

        text = stream.getvalue()
        self.assertNotIn("\x1b", text)
        self.assertEqual(
            text.splitlines(),
            [
                "[parse 1/2] Autosave 711.a7s",
                "  [data] reading + decompressing data.a7s",
                "[parse 1/2] done in 5.6s: sessions=5 player_buildings=37,570",
            ],
        )

    def test_interactive_live_lines_are_truncated_before_terminal_wrap(self):
        stream = FakeTTY()
        progress = probe.Progress(stream=stream, interactive=True, terminal_width=20)

        progress.begin_parse("[parse 1/2] Autosave 711.a7s")
        progress.say("  [session] map=data/a/very/long/path.a7t")

        writes = stream.getvalue().split(probe.Progress.CLEAR_LINE)
        header = writes[0].rstrip("\n")
        live_detail = writes[-1]
        self.assertLessEqual(probe.Progress._display_width(header), 19)
        self.assertLessEqual(probe.Progress._display_width(live_detail), 19)
        self.assertTrue(header.endswith("..."))
        self.assertTrue(live_detail.endswith("..."))

    def test_wide_characters_are_truncated_by_terminal_cells(self):
        stream = FakeTTY()
        progress = probe.Progress(stream=stream, interactive=True, terminal_width=10)

        progress.begin_parse("[p]")
        progress.say("界界界界界")

        live_detail = stream.getvalue().split(probe.Progress.CLEAR_LINE)[-1]
        self.assertLessEqual(probe.Progress._display_width(live_detail), 9)
        self.assertTrue(live_detail.endswith("..."))

    def test_posix_dumb_terminal_falls_back_to_line_logging(self):
        stream = FakeTTY()
        with (
            patch.object(probe.os, "name", "posix"),
            patch.dict(probe.os.environ, {"TERM": "dumb"}),
        ):
            progress = probe.Progress(stream=stream)

        progress.begin_parse("[parse 1/1] Autosave 711.a7s")
        progress.say("  [data] working")
        progress.finish_parse("[parse 1/1] done")

        text = stream.getvalue()
        self.assertNotIn("\x1b", text)
        self.assertEqual(
            text.splitlines(),
            ["[parse 1/1] Autosave 711.a7s", "  [data] working", "[parse 1/1] done"],
        )

    def test_emoji_presentation_sequences_use_cluster_display_width(self):
        self.assertEqual(probe.Progress._display_width("©️"), 2)
        self.assertEqual(probe.Progress._display_width("1️⃣"), 2)

        stream = FakeTTY()
        progress = probe.Progress(stream=stream, interactive=True, terminal_width=10)
        progress.begin_parse("[p]")
        progress.say("©️©️©️©️©️")

        live_detail = stream.getvalue().split(probe.Progress.CLEAR_LINE)[-1]
        self.assertLessEqual(probe.Progress._display_width(live_detail), 9)
        self.assertTrue(live_detail.endswith("..."))

    def test_tty_without_in_place_support_falls_back_to_line_logging(self):
        stream = FakeTTY()
        with patch.object(probe, "_supports_in_place_rendering", return_value=False):
            progress = probe.Progress(stream=stream)

        progress.begin_parse("[parse 1/1] Autosave 711.a7s")
        progress.say("  [data] working")
        progress.finish_parse("[parse 1/1] done")

        text = stream.getvalue()
        self.assertNotIn("\x1b", text)
        self.assertEqual(
            text.splitlines(),
            ["[parse 1/1] Autosave 711.a7s", "  [data] working", "[parse 1/1] done"],
        )

    def test_windows_vt_probe_fails_closed_when_console_mode_is_unavailable(self):
        with patch.object(probe.os, "name", "nt"):
            self.assertFalse(probe._enable_windows_vt(FakeTTY()))

    def test_main_aborts_live_parse_cleanly_before_reraising(self):
        stream = FakeTTY()
        progress = probe.Progress(stream=stream, interactive=True, terminal_width=120)
        fake_save = Path("Autosave 711.a7s")

        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "out"
            with (
                patch.object(probe, "Progress", return_value=progress),
                patch.object(probe, "discover_saves", return_value=[fake_save]),
                patch.object(probe, "canonicalize_save", side_effect=RuntimeError("broken save")),
            ):
                with self.assertRaisesRegex(RuntimeError, "broken save"):
                    probe.main([str(Path(td)), "-o", str(output)])

        text = stream.getvalue()
        self.assertIn("[parse 1/1] failed: RuntimeError: broken save", text)
        self.assertTrue(text.endswith("[parse 1/1] failed: RuntimeError: broken save\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
