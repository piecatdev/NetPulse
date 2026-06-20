from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DeviceRegistry:
    """Maps MAC addresses to friendly names stored in a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._names_by_mac: dict[str, str] = {}

    def load(self) -> None:
        if not self.path.exists():
            self._names_by_mac = {}
            return

        data = json.loads(self.path.read_text(encoding="utf-8"))
        devices: dict[str, Any] = data.get("devices", {})
        self._names_by_mac = {
            self._normalize_mac(mac): str(entry.get("name", "")).strip()
            for mac, entry in devices.items()
            if isinstance(entry, dict) and entry.get("name")
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "devices": {
                mac: {"name": name}
                for mac, name in sorted(self._names_by_mac.items())
            }
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def get_name(self, mac: str, fallback: str) -> str:
        return self._names_by_mac.get(self._normalize_mac(mac), fallback)

    def has_name(self, mac: str) -> bool:
        return bool(mac) and self._normalize_mac(mac) in self._names_by_mac

    def set_name(self, mac: str, name: str) -> None:
        self._names_by_mac[self._normalize_mac(mac)] = name.strip()
        self.save()

    @staticmethod
    def _normalize_mac(mac: str) -> str:
        return mac.replace("-", ":").lower()
