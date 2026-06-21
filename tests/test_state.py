from __future__ import annotations

import unittest
from pathlib import Path

from netpulse.models import ScanResult
from netpulse.persistence import DeviceRegistry
from netpulse.state import NetworkState


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
        self.assertTrue(all(device.online for device in state.devices.values()))

        state.apply_scan_results([ScanResult("192.168.1.1", "aa:bb:cc:dd:ee:01", 5.0)])

        offline = state.devices["aa:bb:cc:dd:ee:50"]
        self.assertFalse(offline.online)


if __name__ == "__main__":
    unittest.main()
