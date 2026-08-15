import io
import os
import unittest
from unittest.mock import patch

import anno_save_probe as probe


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


class TerminalEdgeCaseTests(unittest.TestCase):
    def test_posix_unset_term_falls_back_to_line_logging(self):
        stream = FakeTTY()
        with (
            patch.object(probe.os, "name", "posix"),
            patch.dict(probe.os.environ, {}, clear=True),
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

    def test_live_lines_sanitize_tabs_before_width_measurement(self):
        progress = probe.Progress(stream=FakeTTY(), interactive=True, terminal_width=20)
        fitted = progress._fit_live_line("12345678\t1234567")

        self.assertNotIn("\t", fitted)
        self.assertLessEqual(probe.Progress._display_width(fitted), 19)

    def test_live_lines_sanitize_terminal_control_characters(self):
        progress = probe.Progress(stream=FakeTTY(), interactive=True, terminal_width=80)
        fitted = progress._fit_live_line("save\x1b[2A\bname")

        self.assertNotIn("\x1b", fitted)
        self.assertNotIn("\b", fitted)
        self.assertEqual(fitted, "save [2A name")

    def test_finish_parse_accounts_for_header_reflow_after_resize(self):
        stream = FakeTTY()
        sizes = [os.terminal_size((40, 24)), os.terminal_size((20, 24))]
        progress = probe.Progress(stream=stream, interactive=True)

        with patch.object(probe.shutil, "get_terminal_size", side_effect=sizes):
            progress.begin_parse("[parse 1/1] Autosave 1234567890.a7s")
            progress.finish_parse("[parse 1/1] done")

        text = stream.getvalue()
        self.assertEqual(text.count(probe.Progress.CURSOR_UP), 2)
        self.assertTrue(text.endswith("[parse 1/1] done\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)