from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from netpulse.models import ScanResult
from netpulse.network import (
    MAX_PING_TIMEOUT_SECONDS,
    MAX_SCAN_CONCURRENCY,
    MAX_SCAN_INTERVAL_SECONDS,
    NetworkEngine,
)


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

    def test_ping_command_never_emits_zero_timeout(self) -> None:
        engine = NetworkEngine("192.168.1.0/24", timeout=0.0001)

        self.assertEqual(engine._ping_command("192.168.1.10", "darwin")[4], "1")
        self.assertEqual(engine._ping_command("192.168.1.10", "linux")[4], "1")

    def test_engine_rejects_non_finite_and_excessive_limits(self) -> None:
        invalid_options = (
            {"interval": float("nan")},
            {"interval": MAX_SCAN_INTERVAL_SECONDS + 1},
            {"timeout": float("inf")},
            {"timeout": MAX_PING_TIMEOUT_SECONDS + 1},
            {"concurrency": MAX_SCAN_CONCURRENCY + 1},
        )

        for options in invalid_options:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    NetworkEngine("192.168.1.0/24", **options)

    def test_engine_accepts_maximum_limits(self) -> None:
        engine = NetworkEngine(
            "192.168.1.0/24",
            interval=MAX_SCAN_INTERVAL_SECONDS,
            timeout=MAX_PING_TIMEOUT_SECONDS,
            concurrency=MAX_SCAN_CONCURRENCY,
        )

        self.assertEqual(engine.interval, MAX_SCAN_INTERVAL_SECONDS)
        self.assertEqual(engine.timeout, MAX_PING_TIMEOUT_SECONDS)
        self.assertEqual(engine.concurrency, MAX_SCAN_CONCURRENCY)

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


class NetworkEngineScanRejectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_broad_ipv4_deep_scan_is_rejected_before_probing(self) -> None:
        engine = NetworkEngine("10.0.0.0/8", deep_scan=True)
        engine._read_arp_table = AsyncMock(return_value={})
        engine._ping_host = AsyncMock()

        with self.assertRaisesRegex(ValueError, "maximum"):
            await engine.scan_once()

        engine._ping_host.assert_not_awaited()


class NetworkEnginePingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = NetworkEngine("192.0.2.0/30")

    async def test_successful_ping_does_not_kill_exited_process(self) -> None:
        process = MagicMock()
        process.returncode = 0
        process.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await self.engine._ping_host("192.0.2.1")

        self.assertIsNotNone(result)
        process.kill.assert_not_called()
        process.wait.assert_awaited_once()

    async def test_nonzero_ping_does_not_kill_exited_process(self) -> None:
        process = MagicMock()
        process.returncode = 1
        process.wait = AsyncMock(return_value=1)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await self.engine._ping_host("192.0.2.1")

        self.assertIsNone(result)
        process.kill.assert_not_called()
        process.wait.assert_awaited_once()

    async def test_timed_out_ping_is_killed_and_reaped(self) -> None:
        process = MagicMock()
        process.returncode = None
        process.wait = AsyncMock(side_effect=[asyncio.TimeoutError, -9])

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await self.engine._ping_host("192.0.2.1")

        self.assertIsNone(result)
        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.await_count, 2)

    async def test_cancelled_ping_is_killed_reaped_and_propagated(self) -> None:
        process = MagicMock()
        process.returncode = None
        waiting = asyncio.Event()
        wait_calls = 0

        async def wait() -> int:
            nonlocal wait_calls
            wait_calls += 1
            if wait_calls == 1:
                waiting.set()
                await asyncio.Future()
            return -9

        process.wait = AsyncMock(side_effect=wait)
        create_process = AsyncMock(return_value=process)

        with patch("asyncio.create_subprocess_exec", create_process):
            task = asyncio.create_task(self.engine._ping_host("192.0.2.1"))
            await waiting.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.await_count, 2)

    async def test_cleanup_failure_does_not_mask_cancellation(self) -> None:
        process = MagicMock()
        process.returncode = None
        waiting = asyncio.Event()
        wait_calls = 0

        async def wait() -> int:
            nonlocal wait_calls
            wait_calls += 1
            if wait_calls == 1:
                waiting.set()
                await asyncio.Future()
            return -9

        process.wait = AsyncMock(side_effect=wait)
        process.kill.side_effect = RuntimeError("cleanup failed")

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            task = asyncio.create_task(self.engine._ping_host("192.0.2.1"))
            await waiting.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.await_count, 2)


class NetworkEngineScanTests(unittest.IsolatedAsyncioTestCase):
    async def test_arp_is_read_once_and_arp_only_devices_are_preserved(self) -> None:
        engine = NetworkEngine("192.0.2.0/29")
        engine._read_arp_table = AsyncMock(
            return_value={
                "192.0.2.2": "00:11:22:33:44:02",
                "192.0.2.3": "00:11:22:33:44:03",
            }
        )
        engine._ping_host = AsyncMock(
            side_effect=lambda ip: (
                ScanResult(ip=ip, mac="", latency_ms=1.0, hostname=None)
                if ip == "192.0.2.2"
                else None
            )
        )

        results = await engine.scan_once()

        engine._read_arp_table.assert_awaited_once_with()
        self.assertEqual(
            {(result.ip, result.mac, result.latency_ms) for result in results},
            {
                ("192.0.2.2", "00:11:22:33:44:02", 1.0),
                ("192.0.2.3", "00:11:22:33:44:03", None),
            },
        )

    async def test_ipv6_64_deep_scan_is_rejected_before_probing(self) -> None:
        engine = NetworkEngine("2001:db8::/64", deep_scan=True)
        engine._read_arp_table = AsyncMock(return_value={})
        engine._ping_host = AsyncMock()

        with self.assertRaisesRegex(ValueError, "maximum"):
            await engine.scan_once()

        engine._ping_host.assert_not_awaited()

    async def test_probe_concurrency_is_bounded(self) -> None:
        engine = NetworkEngine("192.0.2.0/28", concurrency=3, deep_scan=True)
        engine._read_arp_table = AsyncMock(return_value={})
        active = 0
        maximum_active = 0

        async def probe(ip: str) -> ScanResult:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0)
            active -= 1
            return ScanResult(ip=ip, mac="", latency_ms=1.0, hostname=None)

        engine._ping_host = probe

        results = await engine.scan_once()

        self.assertEqual(len(results), 14)
        self.assertEqual(maximum_active, 3)

    async def test_small_deep_scan_completes(self) -> None:
        engine = NetworkEngine("192.0.2.0/30", deep_scan=True)
        engine._read_arp_table = AsyncMock(return_value={})
        engine._ping_host = AsyncMock(
            side_effect=lambda ip: ScanResult(
                ip=ip, mac="", latency_ms=1.0, hostname=None
            )
        )

        results = await engine.scan_once()

        self.assertEqual(
            [result.ip for result in results], ["192.0.2.1", "192.0.2.2"]
        )

    async def test_empty_arp_does_not_expand_oversized_network(self) -> None:
        engine = NetworkEngine("10.0.0.0/8")
        engine._read_arp_table = AsyncMock(return_value={})
        engine._ping_host = AsyncMock()

        with self.assertRaisesRegex(ValueError, "empty ARP fallback"):
            await engine.scan_once()

        engine._ping_host.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
