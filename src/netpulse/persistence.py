from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class RegistryError(ValueError):
    """Raised when the device registry cannot be loaded or saved."""


class DeviceRegistry:
    """Maps MAC addresses to friendly names stored in a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._names_by_mac: dict[str, str] = {}
        self._loaded_bytes: bytes | None = None
        self._baseline_known = False

    def load(self) -> None:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            self._names_by_mac = {}
            self._loaded_bytes = None
            self._baseline_known = True
            return
        except OSError as exc:
            raise RegistryError(f"Cannot read device registry {self.path}: {exc}") from exc

        try:
            data = json.loads(raw.decode("utf-8"))
        except UnicodeError as exc:
            raise RegistryError(f"Invalid UTF-8 in device registry {self.path}") from exc
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
        self._loaded_bytes = raw
        self._baseline_known = True

    def save(self) -> None:
        payload = {
            "devices": {
                mac: {"name": name}
                for mac, name in sorted(self._names_by_mac.items())
            }
        }
        temporary_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self._baseline_known:
                try:
                    current_bytes = self.path.read_bytes()
                except FileNotFoundError:
                    current_bytes = None
                if current_bytes != self._loaded_bytes:
                    raise RegistryError(
                        f"Device registry {self.path} changed since it was loaded; "
                        "reload it before saving"
                    )

            # Atomic replacement prevents torn files. The optimistic comparison
            # above catches stale writers, but cannot serialize two processes that
            # pass it simultaneously; portable inter-process locking needs more
            # than the Python standard library.
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(payload, temporary, indent=2)
                temporary.flush()
                os.fsync(temporary.fileno())

            os.replace(temporary_path, self.path)
            temporary_path = None
            self._loaded_bytes = self.path.read_bytes()
            self._baseline_known = True
        except RegistryError:
            raise
        except (OSError, UnicodeError) as exc:
            raise RegistryError(f"Cannot save device registry {self.path}: {exc}") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    # Preserve the original save error; a uniquely named temp
                    # file is safer than risking removal of the live registry.
                    pass

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
