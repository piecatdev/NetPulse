from __future__ import annotations

from collections import deque
from datetime import datetime

from .intelligence import DeviceIntelligence
from .memory import NetworkMemory, NetworkMemoryAnalyzer
from .models import Device, NetworkEvent, ScanResult
from .persistence import DeviceRegistry
from .storage import HistoryStore


class NetworkState:
    def __init__(
        self,
        registry: DeviceRegistry,
        *,
        history: HistoryStore | None = None,
        gateway_ip: str | None = None,
        max_events: int = 120,
    ) -> None:
        self.registry = registry
        self.history = history
        self.gateway_ip = gateway_ip
        self.intelligence = DeviceIntelligence()
        self.memory_analyzer = NetworkMemoryAnalyzer()
        self.devices: dict[str, Device] = {}
        self.events: deque[NetworkEvent] = deque(maxlen=max_events)
        self.event_timeline_by_device: dict[str, deque[tuple[str, str, str]]] = {}
        self.latency_samples: dict[str, deque[float]] = {}
        self.scanning = False
        self.last_scan_at: datetime | None = None
        self.selected_device_id: str | None = None
        self.view_mode = "table"
        self.last_scan_count = 0
        self.last_action = "ready"
        self.persistence_error: str | None = None
        self.memory_scroll_offset = 0
        self.network_memory = NetworkMemory(
            health_score=100,
            trust_score=100,
            drift_label="learning",
            summary="Waiting for first scan",
            findings=(),
        )
        self._alerted_unknown_ids: set[str] = set()
        self._alerted_latency_ids: set[str] = set()

    def apply_scan_results(self, results: list[ScanResult]) -> None:
        now = datetime.now()
        seen_ids: set[str] = set()
        prior_records = []
        if self.history is not None:
            try:
                prior_records = self.history.device_records()
                self.persistence_error = None
            except Exception as exc:
                self.persistence_error = str(exc)

        for result in results:
            device_id = result.mac.lower() if result.mac else result.ip
            seen_ids.add(device_id)
            fallback_name = result.hostname or f"Host {result.ip}"
            name = self.registry.get_name(result.mac, fallback_name)
            known = self.registry.has_name(result.mac)
            (
                vendor,
                device_type,
                risk_label,
                risk_score,
                confidence,
                identity_signals,
            ) = self.intelligence.classify(
                result,
                known=known,
                gateway_ip=self.gateway_ip,
            )

            existing = self.devices.get(device_id)
            if existing is None:
                self.devices[device_id] = Device(
                    ip=result.ip,
                    mac=result.mac,
                    name=name,
                    online=True,
                    known=known,
                    vendor=vendor,
                    device_type=device_type,
                    risk_label=risk_label,
                    risk_score=risk_score,
                    confidence=confidence,
                    identity_signals=identity_signals,
                    latency_ms=result.latency_ms,
                    first_seen=now,
                    last_seen=now,
                )
                self.add_event(f"Node {name} connected", "success", device_id)
                if not known and device_id not in self._alerted_unknown_ids:
                    self.add_event(
                        f"Alert: new unknown device {name} ({result.ip})",
                        "warning",
                        device_id,
                    )
                    self._alerted_unknown_ids.add(device_id)
            else:
                was_offline = not existing.online
                existing.ip = result.ip
                existing.mac = result.mac
                existing.name = name
                existing.online = True
                existing.known = known
                existing.vendor = vendor
                existing.device_type = device_type
                existing.risk_label = risk_label
                existing.risk_score = risk_score
                existing.confidence = confidence
                existing.identity_signals = identity_signals
                existing.latency_ms = result.latency_ms
                existing.last_seen = now
                if was_offline:
                    self.add_event(f"Node {name} reconnected", "success", device_id)

            if result.latency_ms is not None:
                samples = self.latency_samples.setdefault(device_id, deque(maxlen=24))
                samples.append(result.latency_ms)
                if result.latency_ms > 350 and device_id not in self._alerted_latency_ids:
                    self.add_event(
                        f"Alert: high latency on {name} ({result.latency_ms:.0f} ms)",
                        "warning",
                        device_id,
                    )
                    self._alerted_latency_ids.add(device_id)
                elif result.latency_ms <= 200:
                    self._alerted_latency_ids.discard(device_id)

        for device_id, device in self.devices.items():
            if device_id not in seen_ids and device.online:
                device.online = False
                self.add_event(f"Node {device.name} disconnected", "warning", device_id)

        self.last_scan_at = now
        self.last_scan_count = len(results)
        self._ensure_selection()
        self.network_memory = self.memory_analyzer.analyze(
            prior_records,
            self.sorted_devices(),
            seen_ids,
        )
        self._clamp_memory_scroll()
        if self.network_memory.drift_label in {"medium", "high"}:
            self.add_event(f"Network drift: {self.network_memory.summary}", "warning")
        if self.history is not None:
            try:
                self.history.record_snapshot(self.devices.values())
                self.persistence_error = None
            except Exception as exc:
                self.persistence_error = str(exc)

    def add_event(self, message: str, level: str = "info", device_id: str | None = None) -> None:
        event = NetworkEvent(datetime.now(), message, level)
        self.events.appendleft(event)
        if device_id is not None:
            timeline = self.event_timeline_by_device.setdefault(device_id, deque(maxlen=20))
            timeline.appendleft((event.timestamp.isoformat(timespec="seconds"), level, message))
        if self.history is not None:
            try:
                self.history.record_event(event, device_id)
                self.persistence_error = None
            except Exception as exc:
                self.persistence_error = str(exc)

    def sorted_devices(self) -> list[Device]:
        return sorted(
            self.devices.values(),
            key=lambda item: (not item.online, not item.known, item.name.lower(), item.ip),
        )

    def attention_devices(self) -> list[Device]:
        def weight(device: Device) -> tuple[int, int, str]:
            type_weight = {
                "gateway": 0,
                "storage": 1,
                "host": 2,
                "mobile": 3,
                "iot": 4,
                "printer": 5,
                "camera": 6,
            }.get(device.device_type, 5)
            if device.device_type == "gateway":
                risk_weight = 0
            elif device.risk_label in {"unknown", "watch"}:
                risk_weight = 1
            elif not device.online:
                risk_weight = 2
            else:
                risk_weight = 3
            return (risk_weight, type_weight, device.ip)

        return sorted(self.devices.values(), key=weight)

    def selected_device(self) -> Device | None:
        if self.selected_device_id is None:
            return None
        return self.devices.get(self.selected_device_id)

    def visible_devices(self, page_size: int) -> tuple[list[Device], int, int]:
        devices = self.sorted_devices()
        if not devices:
            return [], 0, 0
        ids = [device.id for device in devices]
        selected_index = ids.index(self.selected_device_id) if self.selected_device_id in ids else 0
        page = selected_index // page_size
        start = page * page_size
        end = start + page_size
        total_pages = (len(devices) + page_size - 1) // page_size
        return devices[start:end], page + 1, total_pages

    def move_selection(self, offset: int) -> None:
        self._move_selection_in(self.sorted_devices(), offset)

    def move_attention_selection(self, offset: int) -> None:
        self._move_selection_in(self.attention_devices(), offset)

    def _move_selection_in(self, devices: list[Device], offset: int) -> None:
        if not devices:
            self.selected_device_id = None
            return

        ids = [device.id for device in devices]
        if self.selected_device_id not in ids:
            self.selected_device_id = ids[0]
            return

        current = ids.index(self.selected_device_id)
        self.selected_device_id = ids[(current + offset) % len(ids)]
        selected = self.selected_device()
        if selected is not None:
            self.last_action = f"focus {selected.ip}"
            self.add_event(f"Focus: {selected.name} ({selected.ip})", "info", selected.id)

    def scroll_memory(self, offset: int, page_size: int = 7) -> None:
        findings_count = len(self.network_memory.findings)
        if findings_count <= page_size:
            self.memory_scroll_offset = 0
            self.last_action = "memory top"
            return
        maximum = max(0, findings_count - page_size)
        self.memory_scroll_offset = max(0, min(maximum, self.memory_scroll_offset + offset))
        self.last_action = f"memory {self.memory_scroll_offset + 1}/{findings_count}"

    def visible_memory_findings(self, page_size: int = 7):
        findings = list(self.network_memory.findings)
        if not findings:
            return [], 0, 0
        self._clamp_memory_scroll(page_size)
        start = self.memory_scroll_offset
        end = start + page_size
        total_pages = (len(findings) + page_size - 1) // page_size
        page = min(total_pages, (start + page_size - 1) // page_size + 1)
        return findings[start:end], page, total_pages

    def cycle_view(self) -> None:
        modes = ["table", "map", "memory", "cards"]
        current = modes.index(self.view_mode) if self.view_mode in modes else 0
        self.view_mode = modes[(current + 1) % len(modes)]
        self.last_action = f"view {self.view_mode}"
        self.add_event(f"View changed: {self.view_mode}", "info")

    def _clamp_memory_scroll(self, page_size: int = 7) -> None:
        maximum = max(0, len(self.network_memory.findings) - page_size)
        self.memory_scroll_offset = max(0, min(maximum, self.memory_scroll_offset))

    def selected_timeline(self, limit: int = 6) -> list[tuple[str, str, str]]:
        device = self.selected_device()
        if device is None:
            return []
        timeline = list(self.event_timeline_by_device.get(device.id, []))
        if timeline:
            return timeline[:limit]
        fallback = [
            (
                event.timestamp.isoformat(timespec="seconds"),
                event.level,
                event.message,
            )
            for event in self.events
            if device.name in event.message or device.ip in event.message
        ]
        return fallback[:limit]

    def latency_trend(self, device_id: str) -> str:
        samples = list(self.latency_samples.get(device_id, []))
        if not samples:
            return "no data"
        buckets = ".:-=+*#%"
        maximum = max(samples) or 1
        return "".join(buckets[min(len(buckets) - 1, int(sample / maximum * (len(buckets) - 1)))] for sample in samples[-16:])

    def _ensure_selection(self) -> None:
        devices = self.sorted_devices()
        if not devices:
            self.selected_device_id = None
            return
        ids = {device.id for device in devices}
        if self.selected_device_id not in ids:
            self.selected_device_id = devices[0].id
