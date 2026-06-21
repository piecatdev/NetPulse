from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RegistryError(ValueError):
    """Raised when the device registry cannot be loaded or saved."""


class DeviceRegistry:
    """Maps MAC addresses to friendly names stored in a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._names_by_mac: dict[str, str] = {}

    def load(self) -> None:
        if not self.path.exists():
            self._names_by_mac = {}
            return

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RegistryError(f"Invalid registry JSON in {self.path}: {exc.msg}") from exc

        if not isinstance(data, dict):
            raise RegistryError(f"Invalid registry JSON in {self.path}: expected an object")

        devices: Any = data.get("devices", {})
        if not isinstance(devices, dict):
            raise RegistryError(f"Invalid registry JSON in {self.path}: devices must be an object")

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
        normalized = self._normalize_mac(mac)
        clean_name = name.strip()
        if not normalized:
            raise RegistryError("MAC address cannot be empty")
        if not clean_name:
            raise RegistryError("Device name cannot be empty")
        self._names_by_mac[normalized] = clean_name
        self.save()

    @staticmethod
    def _normalize_mac(mac: str) -> str:
        return mac.replace("-", ":").lower()
