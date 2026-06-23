from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from netpulse.models import Device, NetworkEvent
from netpulse.storage import HistoryStore


class HistoryStoreTests(unittest.TestCase):
    def test_records_snapshot_and_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / "history.db")
            store.connect()
            try:
                device = Device(
                    ip="192.168.1.20",
                    mac="aa:bb:cc:dd:ee:20",
                    name="Workstation",
                    known=True,
                )
                store.record_snapshot([device])
                store.record_event(NetworkEvent(device.last_seen, "Node Workstation connected", "success"), device.id)

                timeline = store.timeline(device.id)
            finally:
                store.close()

        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0][1], "success")
        self.assertIn("Workstation", timeline[0][2])

    def test_returns_device_memory_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / "history.db")
            store.connect()
            try:
                device = Device(
                    ip="192.168.1.20",
                    mac="aa:bb:cc:dd:ee:20",
                    name="Workstation",
                    known=True,
                )
                store.record_snapshot([device])

                records = store.device_records()
            finally:
                store.close()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].device_id, device.id)
        self.assertTrue(records[0].known)

    def test_returns_recent_events_and_latency_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / "history.db")
            store.connect()
            try:
                device = Device(
                    ip="192.168.1.20",
                    mac="aa:bb:cc:dd:ee:20",
                    name="Workstation",
                    latency_ms=25.0,
                )
                store.record_snapshot([device])
                device.latency_ms = 75.0
                store.record_snapshot([device])
                store.record_event(NetworkEvent(device.last_seen, "Latency changed", "info"), device.id)

                events = store.recent_events(limit=1)
                latency = store.latency_summary(limit=1)
            finally:
                store.close()

        self.assertEqual(events[0][1], device.id)
        self.assertEqual(events[0][2], "info")
        self.assertEqual(latency[0][0], device.id)
        self.assertEqual(latency[0][1], 2)
        self.assertEqual(latency[0][2], 50.0)

    def test_prunes_metrics_and_events_older_than_retention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / "history.db", retention_days=7)
            store.connect()
            try:
                old = (datetime.now() - timedelta(days=14)).isoformat(timespec="seconds")
                recent = datetime.now().isoformat(timespec="seconds")
                conn = store._conn()
                conn.execute(
                    "INSERT INTO metrics (device_id, captured_at, online, latency_ms) VALUES (?, ?, ?, ?)",
                    ("old", old, 1, None),
                )
                conn.execute(
                    "INSERT INTO metrics (device_id, captured_at, online, latency_ms) VALUES (?, ?, ?, ?)",
                    ("recent", recent, 1, None),
                )
                conn.execute(
                    "INSERT INTO events (captured_at, device_id, level, message) VALUES (?, ?, ?, ?)",
                    (old, "old", "info", "old event"),
                )
                conn.execute(
                    "INSERT INTO events (captured_at, device_id, level, message) VALUES (?, ?, ?, ?)",
                    (recent, "recent", "info", "recent event"),
                )
                conn.commit()

                store.prune_history()

                metrics = conn.execute("SELECT device_id FROM metrics ORDER BY device_id").fetchall()
                events = conn.execute("SELECT device_id FROM events ORDER BY device_id").fetchall()
            finally:
                store.close()

        self.assertEqual(metrics, [("recent",)])
        self.assertEqual(events, [("recent",)])


if __name__ == "__main__":
    unittest.main()
