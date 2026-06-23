from __future__ import annotations

import unittest

from netpulse.memory import DeviceMemoryRecord, NetworkMemoryAnalyzer
from netpulse.models import Device


class NetworkMemoryAnalyzerTests(unittest.TestCase):
    def test_reports_new_and_missing_devices(self) -> None:
        analyzer = NetworkMemoryAnalyzer()
        prior = [
            DeviceMemoryRecord(
                device_id="aa:bb:cc:dd:ee:01",
                mac="aa:bb:cc:dd:ee:01",
                ip="192.168.1.10",
                name="NAS Vault",
                vendor="Synology",
                device_type="storage",
                risk_label="trusted",
                first_seen="2026-06-20T10:00:00",
                last_seen="2026-06-20T18:00:00",
                known=True,
            )
        ]
        current = [
            Device(
                ip="192.168.1.101",
                mac="72:8f:11:10:01:01",
                name="Unknown Sensor",
                known=False,
                risk_label="watch",
            )
        ]

        memory = analyzer.analyze(prior, current, {current[0].id})

        kinds = {finding.kind for finding in memory.findings}
        self.assertIn("new_device", kinds)
        self.assertIn("missing_device", kinds)
        self.assertEqual(memory.drift_label, "medium")
        self.assertLess(memory.health_score, 100)

    def test_reports_ip_change(self) -> None:
        analyzer = NetworkMemoryAnalyzer()
        prior = [
            DeviceMemoryRecord(
                device_id="aa:bb:cc:dd:ee:01",
                mac="aa:bb:cc:dd:ee:01",
                ip="192.168.1.10",
                name="Studio Laptop",
                vendor="Apple",
                device_type="host",
                risk_label="trusted",
                first_seen="2026-06-20T10:00:00",
                last_seen="2026-06-20T18:00:00",
                known=True,
            )
        ]
        current = [
            Device(
                ip="192.168.1.44",
                mac="aa:bb:cc:dd:ee:01",
                name="Studio Laptop",
                known=True,
                risk_label="trusted",
            )
        ]

        memory = analyzer.analyze(prior, current, {current[0].id})

        self.assertEqual(memory.drift_label, "low")
        self.assertEqual(memory.findings[0].kind, "ip_changed")


if __name__ == "__main__":
    unittest.main()
