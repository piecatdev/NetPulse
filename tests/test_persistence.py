from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from netpulse.persistence import DeviceRegistry, RegistryError


class DeviceRegistryTests(unittest.TestCase):
    def test_load_normalizes_mac_addresses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "devices.json"
            path.write_text(
                '{"devices": {"AA-BB-CC-DD-EE-FF": {"name": "Studio Laptop"}}}',
                encoding="utf-8",
            )

            registry = DeviceRegistry(path)
            registry.load()

            self.assertEqual(registry.get_name("aa:bb:cc:dd:ee:ff", "fallback"), "Studio Laptop")
            self.assertTrue(registry.has_name("AA-BB-CC-DD-EE-FF"))

    def test_load_rejects_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "devices.json"
            path.write_text("{bad json", encoding="utf-8")

            registry = DeviceRegistry(path)

            with self.assertRaises(RegistryError):
                registry.load()

    def test_set_name_rejects_empty_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = DeviceRegistry(Path(directory) / "devices.json")

            with self.assertRaises(RegistryError):
                registry.set_name("aa:bb:cc:dd:ee:ff", "  ")


if __name__ == "__main__":
    unittest.main()
