from __future__ import annotations

import asyncio
import contextlib
import io
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from rich.console import Console

from netpulse.cli import (
    _baseline_findings,
    _memory_scroll_offset,
    _run_scan,
    _run_dashboard_workers,
    build_parser,
    run_history_command,
)
from netpulse.memory import DeviceMemoryRecord
from netpulse.models import Device, NetworkEvent, ScanResult
from netpulse.network import (
    MAX_PING_TIMEOUT_SECONDS,
    MAX_SCAN_CONCURRENCY,
    MAX_SCAN_INTERVAL_SECONDS,
)
from netpulse.storage import HistoryStore


class CliParserTests(unittest.TestCase):
    def test_rejects_non_positive_scan_options(self) -> None:
        parser = build_parser()

        for option in ("--interval", "--timeout", "--concurrency"):
            with self.subTest(option=option):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        parser.parse_args(["192.168.1.0/24", option, "0"])

    def test_rejects_negative_retention_days(self) -> None:
        parser = build_parser()

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["192.168.1.0/24", "--retention-days", "-1"])

    def test_accepts_positive_scan_options(self) -> None:
        parser = build_parser()

        args = parser.parse_args(
            [
                "192.168.1.0/24",
                "--interval",
                "2.5",
                "--timeout",
                "0.2",
                "--concurrency",
                "8",
            ]
        )

        self.assertEqual(args.interval, 2.5)
        self.assertEqual(args.timeout, 0.2)
        self.assertEqual(args.concurrency, 8)

    def test_rejects_non_finite_scan_options(self) -> None:
        parser = build_parser()

        for option, value in (
            ("--interval", "nan"),
            ("--interval", "inf"),
            ("--timeout", "nan"),
            ("--timeout", "inf"),
        ):
            with self.subTest(option=option, value=value):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        parser.parse_args(["192.168.1.0/24", option, value])

    def test_rejects_values_above_scan_limits(self) -> None:
        parser = build_parser()

        for option, value in (
            ("--interval", str(MAX_SCAN_INTERVAL_SECONDS + 1)),
            ("--timeout", str(MAX_PING_TIMEOUT_SECONDS + 1)),
            ("--concurrency", str(MAX_SCAN_CONCURRENCY + 1)),
        ):
            with self.subTest(option=option):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        parser.parse_args(["192.168.1.0/24", option, value])

    def test_accepts_maximum_scan_limits(self) -> None:
        args = build_parser().parse_args(
            [
                "192.168.1.0/24",
                "--interval",
                str(MAX_SCAN_INTERVAL_SECONDS),
                "--timeout",
                str(MAX_PING_TIMEOUT_SECONDS),
                "--concurrency",
                str(MAX_SCAN_CONCURRENCY),
            ]
        )

        self.assertEqual(args.interval, MAX_SCAN_INTERVAL_SECONDS)
        self.assertEqual(args.timeout, MAX_PING_TIMEOUT_SECONDS)
        self.assertEqual(args.concurrency, MAX_SCAN_CONCURRENCY)

    def test_rejects_malformed_cidr(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                build_parser().parse_args(["not-a-network"])

        self.assertIn("valid IPv4 or IPv6 CIDR", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_accepts_network_at_host_limit_boundary(self) -> None:
        args = build_parser().parse_args(["192.168.0.0/20"])

        self.assertEqual(args.cidr, "192.168.0.0/20")

    def test_rejects_oversized_ipv4_and_ipv6_networks(self) -> None:
        for cidr in ("192.168.0.0/19", "2001:db8::/115"):
            with self.subTest(cidr=cidr):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        build_parser().parse_args([cidr])

    def test_accepts_zero_retention_days(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["192.168.1.0/24", "--retention-days", "0"])

        self.assertEqual(args.retention_days, 0)

    def test_accepts_demo_mode(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["192.168.1.0/24", "--demo"])

        self.assertTrue(args.demo)
        self.assertEqual(args.demo_view, "map")

    def test_accepts_demo_without_cidr(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--demo"])

        self.assertTrue(args.demo)
        self.assertIsNone(args.cidr)

    def test_accepts_demo_view(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["192.168.1.0/24", "--demo", "--demo-view", "memory"])

        self.assertEqual(args.demo_view, "memory")

    def test_memory_scroll_offsets(self) -> None:
        self.assertEqual(_memory_scroll_offset("up"), -1)
        self.assertEqual(_memory_scroll_offset("down"), 1)
        self.assertEqual(_memory_scroll_offset("left"), -7)
        self.assertEqual(_memory_scroll_offset("right"), 7)

    def test_accepts_memory_without_cidr(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--memory"])

        self.assertTrue(args.memory)
        self.assertIsNone(args.cidr)

    def test_accepts_baseline_without_cidr(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["--baseline", "diff"])

        self.assertEqual(args.baseline, "diff")
        self.assertIsNone(args.cidr)

    def test_memory_command_prints_remembered_devices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "history.db"
            store = HistoryStore(history_path)
            store.connect()
            try:
                device = Device(
                    ip="192.168.1.20",
                    mac="aa:bb:cc:dd:ee:20",
                    name="Workstation",
                    known=True,
                    latency_ms=42.0,
                )
                store.record_snapshot([device])
                store.record_event(NetworkEvent(device.last_seen, "Node Workstation connected", "success"), device.id)
            finally:
                store.close()

            output = io.StringIO()
            console = Console(file=output, force_terminal=False, width=120)
            run_history_command(
                console,
                Namespace(
                    history=history_path,
                    retention_days=0,
                    memory=True,
                    timeline=None,
                    history_limit=10,
                ),
            )

        text = output.getvalue()
        self.assertIn("NetPulse memory", text)
        self.assertIn("Network status:", text)
        self.assertIn("Workstation", text)
        self.assertIn("Latency signals", text)

    def test_timeline_command_matches_device_by_ip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "history.db"
            store = HistoryStore(history_path)
            store.connect()
            try:
                device = Device(
                    ip="192.168.1.30",
                    mac="aa:bb:cc:dd:ee:30",
                    name="NAS",
                    known=True,
                )
                store.record_snapshot([device])
                store.record_event(NetworkEvent(device.last_seen, "Node NAS connected", "success"), device.id)
            finally:
                store.close()

            output = io.StringIO()
            console = Console(file=output, force_terminal=False, width=120)
            run_history_command(
                console,
                Namespace(
                    history=history_path,
                    retention_days=0,
                    memory=False,
                    timeline="192.168.1.30",
                    history_limit=10,
                ),
            )

        text = output.getvalue()
        self.assertIn("NetPulse timeline", text)
        self.assertIn("Node NAS connected", text)

    def test_baseline_command_reports_new_devices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "history.db"
            store = HistoryStore(history_path)
            store.connect()
            try:
                approved = Device(
                    ip="192.168.1.20",
                    mac="aa:bb:cc:dd:ee:20",
                    name="Workstation",
                    known=True,
                )
                store.record_snapshot([approved])
                store.save_baseline(store.device_records())
                current = Device(
                    ip="192.168.1.30",
                    mac="aa:bb:cc:dd:ee:30",
                    name="NAS",
                    known=False,
                )
                store.record_snapshot([approved, current])
            finally:
                store.close()

            output = io.StringIO()
            console = Console(file=output, force_terminal=False, width=120)
            run_history_command(
                console,
                Namespace(
                    history=history_path,
                    retention_days=0,
                    memory=False,
                    timeline=None,
                    baseline="diff",
                    history_limit=10,
                ),
            )

        text = output.getvalue()
        self.assertIn("NetPulse baseline diff", text)
        self.assertIn("new", text)
        self.assertIn("NAS", text)

    def test_baseline_findings_reports_missing_and_changed_devices(self) -> None:
        baseline = [
            DeviceMemoryRecord(
                device_id="aa",
                mac="aa",
                ip="192.168.1.20",
                name="Workstation",
                vendor="Unknown vendor",
                device_type="host",
                risk_label="trusted",
                first_seen="",
                last_seen="",
                known=True,
            ),
            DeviceMemoryRecord(
                device_id="bb",
                mac="bb",
                ip="192.168.1.30",
                name="NAS",
                vendor="Unknown vendor",
                device_type="storage",
                risk_label="trusted",
                first_seen="",
                last_seen="",
                known=True,
            ),
        ]
        current = [
            DeviceMemoryRecord(
                device_id="aa",
                mac="aa",
                ip="192.168.1.44",
                name="Workstation",
                vendor="Unknown vendor",
                device_type="host",
                risk_label="watch",
                first_seen="",
                last_seen="",
                known=True,
            )
        ]

        findings = _baseline_findings(baseline, current)

        kinds = [finding[0] for finding in findings]
        self.assertIn("ip", kinds)
        self.assertIn("risk", kinds)
        self.assertIn("missing", kinds)


class DashboardWorkerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_quit_cancels_workers_quietly(self) -> None:
        stop_event = asyncio.Event()
        worker_cancelled = asyncio.Event()

        async def request_quit() -> None:
            stop_event.set()

        async def worker() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                worker_cancelled.set()

        quit_task = asyncio.create_task(request_quit())
        worker_task = asyncio.create_task(worker())
        await _run_dashboard_workers(stop_event, quit_task, worker_task)

        self.assertTrue(worker_cancelled.is_set())
        self.assertTrue(worker_task.cancelled())

    async def test_scan_failure_is_propagated_and_input_is_cancelled(self) -> None:
        stop_event = asyncio.Event()
        sibling_cancelled = asyncio.Event()

        async def fail_scan() -> None:
            await asyncio.sleep(0)
            raise RuntimeError("scan failed")

        async def input_worker() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                sibling_cancelled.set()

        scan_task = asyncio.create_task(fail_scan())
        input_task = asyncio.create_task(input_worker())
        with self.assertRaisesRegex(RuntimeError, "scan failed"):
            await _run_dashboard_workers(stop_event, scan_task, input_task)

        self.assertTrue(stop_event.is_set())
        self.assertTrue(sibling_cancelled.is_set())
        self.assertTrue(input_task.cancelled())

    async def test_input_failure_is_propagated_and_scan_is_cancelled(self) -> None:
        stop_event = asyncio.Event()
        sibling_cancelled = asyncio.Event()

        async def scan_worker() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                sibling_cancelled.set()

        async def fail_input() -> None:
            await asyncio.sleep(0)
            raise OSError("input failed")

        scan_task = asyncio.create_task(scan_worker())
        input_task = asyncio.create_task(fail_input())
        with self.assertRaisesRegex(OSError, "input failed"):
            await _run_dashboard_workers(stop_event, scan_task, input_task)

        self.assertTrue(stop_event.is_set())
        self.assertTrue(sibling_cancelled.is_set())
        self.assertTrue(scan_task.cancelled())


class ScanRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_applies_one_authoritative_scan_result(self) -> None:
        arp_only_device = ScanResult(
            ip="192.168.1.24",
            mac="00:11:32:10:00:24",
            latency_ms=None,
            hostname=None,
        )
        engine = MagicMock()
        engine.deep_scan = False
        engine.host_count = 254
        engine.scan_once = AsyncMock(return_value=[arp_only_device])
        state = MagicMock()

        await _run_scan(engine, state)

        engine.scan_once.assert_awaited_once_with()
        state.apply_scan_results.assert_called_once_with([arp_only_device])
        self.assertEqual(state.add_event.call_count, 2)
        self.assertIn("Scan started", state.add_event.call_args_list[0].args[0])
        self.assertIn("Scan complete", state.add_event.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()
