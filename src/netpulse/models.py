from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Device:
    """Runtime state for a device discovered on the local network."""

    ip: str
    mac: str
    name: str
    online: bool = True
    known: bool = False
    vendor: str = "Unknown vendor"
    device_type: str = "host"
    risk_label: str = "unknown"
    risk_score: int = 50
    latency_ms: float | None = None
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)

    @property
    def id(self) -> str:
        return self.mac.lower() if self.mac else self.ip


@dataclass(slots=True)
class ScanResult:
    ip: str
    mac: str
    latency_ms: float | None
    hostname: str | None = None


@dataclass(slots=True)
class NetworkEvent:
    timestamp: datetime
    message: str
    level: str = "info"
