from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from rich.console import Console

from netpulse.cli import _baseline_findings, _memory_scroll_offset, build_parser, run_history_command
from netpulse.memory import DeviceMemoryRecord
from netpulse.models import Device, NetworkEvent
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


if __name__ == "__main__":
    unittest.main()
