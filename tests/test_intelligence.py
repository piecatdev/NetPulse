from __future__ import annotations

import unittest

from netpulse.intelligence import DeviceIntelligence
from netpulse.models import ScanResult


class DeviceIntelligenceTests(unittest.TestCase):
    def test_known_named_device_has_high_confidence(self) -> None:
        intelligence = DeviceIntelligence()

        vendor, device_type, risk_label, _, confidence, signals = intelligence.classify(
            ScanResult("192.168.1.12", "3c:22:fb:10:00:12", 18.0, "Studio-Laptop"),
            known=True,
            gateway_ip="192.168.1.1",
        )

        self.assertEqual(vendor, "Apple")
        self.assertEqual(device_type, "host")
        self.assertEqual(risk_label, "trusted")
        self.assertEqual(confidence, "high")
        self.assertIn("saved name", signals)
        self.assertIn("hostname", signals)
        self.assertIn("mac vendor", signals)

    def test_gateway_ip_is_a_high_confidence_signal(self) -> None:
        intelligence = DeviceIntelligence()

        _, device_type, _, _, confidence, signals = intelligence.classify(
            ScanResult("192.168.1.1", "00:1a:2b:10:00:01", 4.0, None),
            known=False,
            gateway_ip="192.168.1.1",
        )

        self.assertEqual(device_type, "gateway")
        self.assertEqual(confidence, "high")
        self.assertIn("gateway ip", signals)

    def test_vendor_hostname_and_type_hint_give_high_confidence(self) -> None:
        intelligence = DeviceIntelligence()

        vendor, device_type, _, _, confidence, signals = intelligence.classify(
            ScanResult("192.168.1.54", "44:65:0d:10:00:54", 44.0, "Kitchen-Echo"),
            known=False,
            gateway_ip="192.168.1.1",
        )

        self.assertEqual(vendor, "Amazon")
        self.assertEqual(device_type, "iot")
        self.assertEqual(confidence, "high")
        self.assertIn("type hint", signals)

    def test_device_without_mac_or_hostname_has_low_confidence(self) -> None:
        intelligence = DeviceIntelligence()

        vendor, device_type, risk_label, _, confidence, signals = intelligence.classify(
            ScanResult("192.168.1.115", "", None, None),
            known=False,
            gateway_ip="192.168.1.1",
        )

        self.assertEqual(vendor, "Unknown vendor")
        self.assertEqual(device_type, "host")
        self.assertEqual(risk_label, "watch")
        self.assertEqual(confidence, "low")
        self.assertEqual(signals, ())

    def test_hostname_identifies_printer(self) -> None:
        intelligence = DeviceIntelligence()

        _, device_type, _, _, confidence, signals = intelligence.classify(
            ScanResult("192.168.1.45", "aa:bb:cc:10:00:45", 12.0, "Office-Printer"),
            known=False,
            gateway_ip="192.168.1.1",
        )

        self.assertEqual(device_type, "printer")
        self.assertEqual(confidence, "medium")
        self.assertIn("type hint", signals)

    def test_hostname_identifies_camera(self) -> None:
        intelligence = DeviceIntelligence()

        _, device_type, _, _, confidence, signals = intelligence.classify(
            ScanResult("192.168.1.60", "aa:bb:cc:10:00:60", 20.0, "front-camera"),
            known=False,
            gateway_ip="192.168.1.1",
        )

        self.assertEqual(device_type, "camera")
        self.assertEqual(confidence, "medium")
        self.assertIn("type hint", signals)

    def test_espressif_vendor_identifies_iot_device(self) -> None:
        intelligence = DeviceIntelligence()

        vendor, device_type, _, _, confidence, signals = intelligence.classify(
            ScanResult("192.168.1.70", "24:0a:c4:10:00:70", None, None),
            known=False,
            gateway_ip="192.168.1.1",
        )

        self.assertEqual(vendor, "Espressif")
        self.assertEqual(device_type, "iot")
        self.assertEqual(confidence, "medium")
        self.assertIn("mac vendor", signals)

    def test_hostname_identifies_router(self) -> None:
        intelligence = DeviceIntelligence()

        _, device_type, _, _, confidence, signals = intelligence.classify(
            ScanResult("192.168.1.2", "aa:bb:cc:10:00:02", 3.0, "openwrt-lab"),
            known=False,
            gateway_ip="192.168.1.1",
        )

        self.assertEqual(device_type, "gateway")
        self.assertEqual(confidence, "medium")
        self.assertIn("type hint", signals)


if __name__ == "__main__":
    unittest.main()
