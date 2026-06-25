from __future__ import annotations

import unittest

from netpulse.network import NetworkEngine


class NetworkEnginePlatformTests(unittest.TestCase):
    def test_ping_command_uses_windows_timeout_milliseconds(self) -> None:
        engine = NetworkEngine("192.168.1.0/24", timeout=0.25)

        self.assertEqual(
            engine._ping_command("192.168.1.10", "windows"),
            ["ping", "-n", "1", "-w", "250", "192.168.1.10"],
        )

    def test_ping_command_uses_linux_timeout_seconds(self) -> None:
        engine = NetworkEngine("192.168.1.0/24", timeout=0.25)

        self.assertEqual(
            engine._ping_command("192.168.1.10", "linux"),
            ["ping", "-c", "1", "-W", "1", "192.168.1.10"],
        )

    def test_ping_command_uses_macos_timeout_milliseconds(self) -> None:
        engine = NetworkEngine("192.168.1.0/24", timeout=0.25)

        self.assertEqual(
            engine._ping_command("192.168.1.10", "darwin"),
            ["ping", "-c", "1", "-W", "250", "192.168.1.10"],
        )

    def test_ping_command_never_uses_zero_timeout(self) -> None:
        engine = NetworkEngine("192.168.1.0/24", timeout=0.0)

        self.assertEqual(engine._ping_command("192.168.1.10", "darwin")[4], "1")
        self.assertEqual(engine._ping_command("192.168.1.10", "linux")[4], "1")


if __name__ == "__main__":
    unittest.main()
