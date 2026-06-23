from __future__ import annotations

import unittest
import io
from pathlib import Path

from rich.console import Console

from netpulse.memory import DriftFinding, NetworkMemory
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


if __name__ == "__main__":
    unittest.main()
