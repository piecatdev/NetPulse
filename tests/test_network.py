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

    def test_parse_arp_table_accepts_windows_output(self) -> None:
        text = """
Interface: 192.168.1.20 --- 0x13
  Internet Address      Physical Address      Type
  192.168.1.1           00-1a-2b-10-00-01     dynamic
  192.168.1.24          00-11-32-10-00-24     dynamic
"""

        self.assertEqual(
            NetworkEngine._parse_arp_table(text),
            {
                "192.168.1.1": "00:1a:2b:10:00:01",
                "192.168.1.24": "00:11:32:10:00:24",
            },
        )

    def test_parse_arp_table_accepts_macos_output(self) -> None:
        text = """
? (192.168.1.1) at 0:1a:2b:10:0:1 on en0 ifscope [ethernet]
? (192.168.1.24) at 0:11:32:10:0:24 on en0 ifscope [ethernet]
"""

        self.assertEqual(
            NetworkEngine._parse_arp_table(text),
            {
                "192.168.1.1": "00:1a:2b:10:00:01",
                "192.168.1.24": "00:11:32:10:00:24",
            },
        )

    def test_parse_arp_table_accepts_linux_output(self) -> None:
        text = """
gateway (192.168.1.1) at 00:1a:2b:10:00:01 [ether] on wlan0
nas.local (192.168.1.24) at 00:11:32:10:00:24 [ether] on wlan0
"""

        self.assertEqual(
            NetworkEngine._parse_arp_table(text),
            {
                "192.168.1.1": "00:1a:2b:10:00:01",
                "192.168.1.24": "00:11:32:10:00:24",
            },
        )

    def test_gateway_command_is_os_specific(self) -> None:
        self.assertEqual(
            NetworkEngine._gateway_command("windows"),
            ["route", "print", "-4", "0.0.0.0"],
        )
        self.assertEqual(
            NetworkEngine._gateway_command("darwin"),
            ["route", "-n", "get", "default"],
        )
        self.assertEqual(
            NetworkEngine._gateway_command("linux"),
            ["ip", "route", "show", "default"],
        )

    def test_gateway_candidates_accept_windows_output(self) -> None:
        text = """
IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0      192.168.1.1    192.168.1.20     25
"""

        self.assertEqual(NetworkEngine._gateway_candidates(text), ["192.168.1.1"])

    def test_gateway_candidates_accept_macos_output(self) -> None:
        text = """
   route to: default
destination: default
       mask: default
    gateway: 192.168.1.1
  interface: en0
"""

        self.assertEqual(NetworkEngine._gateway_candidates(text), ["192.168.1.1"])

    def test_gateway_candidates_accept_linux_output(self) -> None:
        text = "default via 192.168.1.1 dev wlan0 proto dhcp src 192.168.1.20 metric 600"

        self.assertEqual(NetworkEngine._gateway_candidates(text), ["192.168.1.1"])

    def test_ip_in_network_rejects_invalid_gateway_candidate(self) -> None:
        engine = NetworkEngine("192.168.1.0/24")

        self.assertTrue(engine._ip_in_network("192.168.1.1"))
        self.assertFalse(engine._ip_in_network("10.0.0.1"))
        self.assertFalse(engine._ip_in_network("not-an-ip"))


if __name__ == "__main__":
    unittest.main()
