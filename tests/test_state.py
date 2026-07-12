from __future__ import annotations

import asyncio
import threading
import unittest
import tempfile
from pathlib import Path

from netpulse.memory import DriftFinding, NetworkMemory
from netpulse.models import ScanResult
from netpulse.persistence import DeviceRegistry
from netpulse.state import NetworkState
from netpulse.storage import HistoryStore


class NetworkStateTests(unittest.TestCase):
    def test_scan_results_create_and_disconnect_devices(self) -> None:
        registry = DeviceRegistry(Path("unused.json"))
        state = NetworkState(registry, gateway_ip="192.168.1.1")

        state.apply_scan_results(
            [
                ScanResult("192.168.1.1", "aa:bb:cc:dd:ee:01", 4.0),
                ScanResult("192.168.1.50", "aa:bb:cc:dd:ee:50", 12.0),
            ]
        )

        self.assertEqual(len(state.devices), 2)
        self.assertEqual(state.selected_device().ip, "192.168.1.1")
        self.assertEqual(state.selected_device().confidence, "high")
        self.assertIn("gateway ip", state.selected_device().identity_signals)
        self.assertTrue(all(device.online for device in state.devices.values()))

        state.apply_scan_results([ScanResult("192.168.1.1", "aa:bb:cc:dd:ee:01", 5.0)])

        offline = state.devices["aa:bb:cc:dd:ee:50"]
        self.assertFalse(offline.online)

    def test_network_memory_compares_against_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history = HistoryStore(Path(directory) / "history.db")
            history.connect()
            try:
                registry = DeviceRegistry(Path("unused.json"))
                state = NetworkState(registry, history=history, gateway_ip="192.168.1.1")

                state.apply_scan_results([ScanResult("192.168.1.20", "aa:bb:cc:dd:ee:20", 10.0)])
                self.assertEqual(state.network_memory.drift_label, "learning")

                state.apply_scan_results([ScanResult("192.168.1.30", "aa:bb:cc:dd:ee:30", 14.0)])

                kinds = {finding.kind for finding in state.network_memory.findings}
            finally:
                history.close()

        self.assertIn("new_device", kinds)
        self.assertIn("missing_device", kinds)

    def test_memory_findings_can_scroll(self) -> None:
        registry = DeviceRegistry(Path("unused.json"))
        state = NetworkState(registry)
        state.network_memory = NetworkMemory(
            health_score=70,
            trust_score=80,
            drift_label="medium",
            summary="many changes",
            findings=tuple(
                DriftFinding("new_device", "warning", f"Finding {index}", f"detail {index}")
                for index in range(12)
            ),
        )

        visible, page, total_pages = state.visible_memory_findings(page_size=7)
        self.assertEqual(len(visible), 7)
        self.assertEqual(page, 1)
        self.assertEqual(total_pages, 2)

        state.scroll_memory(7, page_size=7)
        visible, page, total_pages = state.visible_memory_findings(page_size=7)

        self.assertEqual(state.memory_scroll_offset, 5)
        self.assertEqual(visible[0].title, "Finding 5")
        self.assertEqual(page, 2)
        self.assertEqual(total_pages, 2)

        state.scroll_memory(-99, page_size=7)
        self.assertEqual(state.memory_scroll_offset, 0)

    def test_attention_selection_follows_map_order(self) -> None:
        registry = DeviceRegistry(Path("unused.json"))
        state = NetworkState(registry, gateway_ip="192.168.1.1")
        state.apply_scan_results(
            [
                ScanResult("192.168.1.1", "00:1a:2b:10:00:01", 4.0, "Gateway"),
                ScanResult("192.168.1.24", "00:11:32:10:00:24", 9.0, "NAS"),
                ScanResult("192.168.1.101", "72:8f:11:10:01:01", None, "Unknown Sensor"),
            ]
        )

        self.assertEqual(state.selected_device().ip, "192.168.1.1")

        expected_next = state.attention_devices()[1].ip
        state.move_attention_selection(1)

        self.assertEqual(state.selected_device().ip, expected_next)


class AsyncNetworkStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_scan_keeps_loop_responsive_and_orders_history_work(self) -> None:
        started = threading.Event()
        release = threading.Event()
        calls: list[tuple[str, int]] = []

        class BlockingHistory:
            def device_records(self):
                calls.append(("read", threading.get_ident()))
                started.set()
                release.wait()
                return []

            def record_event(self, event, device_id=None):
                calls.append((f"event:{event.message}", threading.get_ident()))

            def record_snapshot(self, devices):
                calls.append(("snapshot", threading.get_ident()))

        loop_thread = threading.get_ident()
        state = NetworkState(DeviceRegistry(Path("unused.json")), history=BlockingHistory())
        task = asyncio.create_task(
            state.apply_scan_results_async(
                [ScanResult("192.168.1.20", "aa:bb:cc:dd:ee:20", 10.0)]
            )
        )
        while not started.is_set():
            await asyncio.sleep(0)

        loop_progressed = False
        await asyncio.sleep(0)
        loop_progressed = True
        self.assertFalse(task.done())
        release.set()
        await task

        self.assertTrue(loop_progressed)
        self.assertEqual(calls[0][0], "read")
        self.assertTrue(calls[1][0].startswith("event:Node"))
        self.assertTrue(calls[2][0].startswith("event:Alert"))
        self.assertEqual(calls[3][0], "snapshot")
        self.assertTrue(all(thread_id != loop_thread for _, thread_id in calls))

    async def test_async_snapshot_failure_sets_persistence_error(self) -> None:
        class FailingHistory:
            def device_records(self):
                return []

            def record_event(self, event, device_id=None):
                return None

            def record_snapshot(self, devices):
                raise OSError("disk unavailable")

        state = NetworkState(DeviceRegistry(Path("unused.json")), history=FailingHistory())

        await state.apply_scan_results_async(
            [ScanResult("192.168.1.20", "aa:bb:cc:dd:ee:20", 10.0)]
        )

        self.assertEqual(state.persistence_error, "disk unavailable")


if __name__ == "__main__":
    unittest.main()
