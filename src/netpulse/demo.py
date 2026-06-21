from __future__ import annotations

from pathlib import Path

from .models import ScanResult
from .persistence import DeviceRegistry


KNOWN_DEMO_DEVICES = {
    "00:1a:2b:10:00:01": "Gateway Router",
    "3c:22:fb:10:00:12": "Studio Laptop",
    "00:09:34:10:00:18": "Workstation",
    "00:11:32:10:00:24": "NAS Vault",
    "f0:18:98:10:00:36": "iPad Desk",
    "bc:92:6b:10:00:42": "Smart TV",
    "44:65:0d:10:00:54": "Kitchen Echo",
    "a4:77:33:10:00:67": "Hallway Nest",
    "dc:a6:32:10:00:88": "Pi Monitor",
}


def demo_scan_results() -> list[ScanResult]:
    """Return a synthetic LAN snapshot for screenshots and demos."""

    return [
        ScanResult("192.168.1.1", "00:1a:2b:10:00:01", 4.0, "Gateway Router"),
        ScanResult("192.168.1.12", "3c:22:fb:10:00:12", 18.0, "Studio Laptop"),
        ScanResult("192.168.1.18", "00:09:34:10:00:18", 22.0, "Workstation"),
        ScanResult("192.168.1.24", "00:11:32:10:00:24", 9.0, "NAS Vault"),
        ScanResult("192.168.1.36", "f0:18:98:10:00:36", 35.0, "iPad Desk"),
        ScanResult("192.168.1.42", "bc:92:6b:10:00:42", 28.0, "Smart TV"),
        ScanResult("192.168.1.54", "44:65:0d:10:00:54", 44.0, "Kitchen Echo"),
        ScanResult("192.168.1.67", "a4:77:33:10:00:67", 31.0, "Hallway Nest"),
        ScanResult("192.168.1.88", "dc:a6:32:10:00:88", 12.0, "Pi Monitor"),
        ScanResult("192.168.1.101", "72:8f:11:10:01:01", None, "Unknown Sensor"),
        ScanResult("192.168.1.115", "", None, "Mystery Host"),
    ]


def demo_registry() -> DeviceRegistry:
    registry = DeviceRegistry(path=Path("demo-devices.json"))
    registry._names_by_mac = KNOWN_DEMO_DEVICES.copy()
    return registry
