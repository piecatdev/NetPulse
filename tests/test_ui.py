from __future__ import annotations

import unittest
import io
from pathlib import Path

from rich.console import Console

from netpulse.memory import DriftFinding, NetworkMemory
from netpulse.models import ScanResult
from netpulse.persistence import DeviceRegistry
from netpulse.state import NetworkState
from netpulse.ui import Dashboard


class DashboardRenderingTests(unittest.TestCase):
    def test_memory_view_renders_scrolled_findings(self) -> None:
        state = NetworkState(DeviceRegistry(Path("unused.json")))
        state.view_mode = "memory"
        state.network_memory = NetworkMemory(
            health_score=72,
            trust_score=81,
            drift_label="medium",
            summary="many changes",
            findings=tuple(
                DriftFinding("new_device", "warning", f"Finding {index}", f"detail {index}")
                for index in range(12)
            ),
        )
        state.scroll_memory(7, page_size=7)

        console = Console(file=io.StringIO(), record=True, width=120, height=36)
        console.print(Dashboard(state).render())
        output = console.export_text(styles=False)

        self.assertIn("Network Memory", output)
        self.assertIn("06 Finding 5", output)
        self.assertNotIn("01 Finding 0", output)

    def test_map_view_renders_clean_network_overview(self) -> None:
        state = NetworkState(DeviceRegistry(Path("unused.json")), gateway_ip="192.168.1.1")
        state.view_mode = "map"
        state.apply_scan_results(
            [
                ScanResult("192.168.1.1", "00:1a:2b:10:00:01", 4.0, "Gateway"),
                ScanResult("192.168.1.24", "00:11:32:10:00:24", 12.0, "NAS"),
                ScanResult("192.168.1.88", "", None, "Mystery Host"),
            ]
        )

        console = Console(file=io.StringIO(), record=True, width=120, height=36)
        console.print(Dashboard(state).render())
        output = console.export_text(styles=False)

        self.assertIn("Network Overview", output)
        self.assertIn("gateway", output)
        self.assertIn("attention", output)
        self.assertIn("Mystery Host", output)
        self.assertNotIn("WAN", output)
        self.assertNotIn("NETPULSE CORE", output)

    def test_detail_view_explains_identity_without_extra_columns(self) -> None:
        state = NetworkState(DeviceRegistry(Path("unused.json")), gateway_ip="192.168.1.1")
        state.apply_scan_results(
            [
                ScanResult("192.168.1.1", "00:1a:2b:10:00:01", 4.0, "Gateway"),
            ]
        )

        console = Console(file=io.StringIO(), record=True, width=120, height=36)
        console.print(Dashboard(state).render())
        output = console.export_text(styles=False)

        self.assertIn("Identity", output)
        self.assertIn("high from", output)
        self.assertIn("gateway ip", output)
        self.assertNotIn("Signals", output)
        self.assertNotIn("Confidence", output)

    def test_card_view_keeps_identity_compact(self) -> None:
        state = NetworkState(DeviceRegistry(Path("unused.json")), gateway_ip="192.168.1.1")
        state.view_mode = "cards"
        state.apply_scan_results(
            [
                ScanResult("192.168.1.1", "00:1a:2b:10:00:01", 4.0, "Gateway"),
                ScanResult("192.168.1.24", "00:11:32:10:00:24", 9.0, "NAS"),
                ScanResult("192.168.1.101", "72:8f:11:10:01:01", None, "Unknown Sensor"),
            ]
        )

        console = Console(file=io.StringIO(), record=True, width=120, height=36)
        console.print(Dashboard(state).render())
        output = console.export_text(styles=False)

        self.assertIn("Device Cards", output)
        self.assertIn("Identity", output)
        self.assertNotIn("Identity            high from", output)


if __name__ == "__main__":
    unittest.main()
