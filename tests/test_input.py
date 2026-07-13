from __future__ import annotations

import unittest
import importlib.util
from unittest import mock

from netpulse.input import KeyboardInput


class KeyboardInputTests(unittest.TestCase):
    def test_map_key_keeps_supported_controls(self) -> None:
        self.assertEqual(KeyboardInput._map_key("q"), "quit")
        self.assertEqual(KeyboardInput._map_key("r"), "refresh")
        self.assertEqual(KeyboardInput._map_key("v"), "view")
        self.assertEqual(KeyboardInput._map_key("up"), "up")
        self.assertEqual(KeyboardInput._map_key("unknown"), "noop")

    def test_posix_poll_returns_empty_for_non_tty_stdin(self) -> None:
        stdin = mock.Mock()
        stdin.isatty.return_value = False

        with mock.patch("sys.stdin", stdin):
            self.assertEqual(KeyboardInput._poll_posix_key(), "")
        stdin.fileno.assert_not_called()

    def test_posix_poll_returns_empty_when_redirected_stdin_has_no_fileno(self) -> None:
        stdin = mock.Mock()
        stdin.isatty.return_value = True
        stdin.fileno.side_effect = OSError("no file descriptor")

        with mock.patch("sys.stdin", stdin):
            self.assertEqual(KeyboardInput._poll_posix_key(), "")

    def test_posix_poll_returns_empty_when_terminal_settings_fail(self) -> None:
        if importlib.util.find_spec("termios") is None:
            self.skipTest("termios is not available on this platform")
        import termios

        stdin = mock.Mock()
        stdin.fileno.return_value = 0
        stdin.isatty.return_value = True

        with mock.patch("sys.stdin", stdin):
            with mock.patch("termios.tcgetattr", side_effect=termios.error):
                self.assertEqual(KeyboardInput._poll_posix_key(), "")


if __name__ == "__main__":
    unittest.main()
