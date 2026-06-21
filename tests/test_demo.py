from __future__ import annotations

import unittest

from netpulse.demo import demo_registry, demo_scan_results


class DemoDatasetTests(unittest.TestCase):
    def test_demo_dataset_uses_clear_synthetic_names(self) -> None:
        results = demo_scan_results()
        names = {result.hostname for result in results}

        self.assertGreaterEqual(len(results), 8)
        self.assertIn("Studio Laptop", names)
        self.assertIn("NAS Vault", names)
        self.assertIn("Unknown Sensor", names)
        self.assertTrue(all(result.ip.startswith("192.168.1.") for result in results))

    def test_demo_registry_marks_common_devices_as_known(self) -> None:
        registry = demo_registry()

        self.assertTrue(registry.has_name("00:1a:2b:10:00:01"))
        self.assertTrue(registry.has_name("3c:22:fb:10:00:12"))
        self.assertFalse(registry.has_name("72:8f:11:10:01:01"))


if __name__ == "__main__":
    unittest.main()
