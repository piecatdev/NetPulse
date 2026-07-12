from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_save_atomically_replaces_existing_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "devices.json"
            path.write_text('{"devices": {}}', encoding="utf-8")
            registry = DeviceRegistry(path)
            registry.load()

            registry.set_name("AA-BB-CC-DD-EE-FF", "Studio Laptop")

            reloaded = DeviceRegistry(path)
            reloaded.load()
            self.assertEqual(
                reloaded.get_name("aa:bb:cc:dd:ee:ff", "fallback"),
                "Studio Laptop",
            )
            self.assertEqual(list(Path(directory).glob(".devices.json.*.tmp")), [])

    def test_write_failure_preserves_previous_bytes_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "devices.json"
            original = b'{"devices": {}}\n'
            path.write_bytes(original)
            registry = DeviceRegistry(path)
            registry.load()
            registry._names_by_mac["aa:bb:cc:dd:ee:ff"] = "Laptop"

            with mock.patch("netpulse.persistence.json.dump", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(RegistryError, "Cannot save"):
                    registry.save()

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).glob(".devices.json.*.tmp")), [])

    def test_replace_failure_preserves_previous_bytes_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "devices.json"
            original = b'{"devices": {}}\n'
            path.write_bytes(original)
            registry = DeviceRegistry(path)
            registry.load()
            registry._names_by_mac["aa:bb:cc:dd:ee:ff"] = "Laptop"

            with mock.patch("netpulse.persistence.os.replace", side_effect=OSError("busy")):
                with self.assertRaisesRegex(RegistryError, "Cannot save"):
                    registry.save()

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).glob(".devices.json.*.tmp")), [])

    def test_load_translates_io_errors(self) -> None:
        registry = DeviceRegistry(Path("devices.json"))

        with mock.patch.object(Path, "read_bytes", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(RegistryError, "Cannot read") as raised:
                registry.load()

        self.assertIsInstance(raised.exception.__cause__, PermissionError)

    def test_stale_writer_must_reload_before_saving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "devices.json"
            original = b'{"devices": {}}\n'
            path.write_bytes(original)
            first = DeviceRegistry(path)
            second = DeviceRegistry(path)
            first.load()
            second.load()

            first.set_name("aa:bb:cc:dd:ee:ff", "First")
            first_bytes = path.read_bytes()
            with self.assertRaisesRegex(RegistryError, "changed since it was loaded"):
                second.set_name("11:22:33:44:55:66", "Second")

            self.assertEqual(path.read_bytes(), first_bytes)
            self.assertEqual(list(Path(directory).glob(".devices.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
