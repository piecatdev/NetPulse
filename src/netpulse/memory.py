from __future__ import annotations

from dataclasses import dataclass

from .models import Device


@dataclass(frozen=True, slots=True)
class DeviceMemoryRecord:
    device_id: str
    mac: str
    ip: str
    name: str
    vendor: str
    device_type: str
    risk_label: str
    first_seen: str
    last_seen: str
    known: bool


@dataclass(frozen=True, slots=True)
class DriftFinding:
    kind: str
    severity: str
    title: str
    detail: str
    device_id: str | None = None


@dataclass(frozen=True, slots=True)
class NetworkMemory:
    health_score: int
    trust_score: int
    drift_label: str
    summary: str
    findings: tuple[DriftFinding, ...]


class NetworkMemoryAnalyzer:
    def analyze(
        self,
        prior_records: list[DeviceMemoryRecord],
        current_devices: list[Device],
        seen_ids: set[str],
    ) -> NetworkMemory:
        if not prior_records:
            return NetworkMemory(
                health_score=100,
                trust_score=self._trust_score(current_devices),
                drift_label="learning",
                summary="Learning first network baseline",
                findings=(
                    DriftFinding(
                        "baseline",
                        "info",
                        "Baseline learning",
                        "No prior device memory exists yet. This scan becomes the first comparison point.",
                    ),
                ),
            )

        prior_by_id = {record.device_id: record for record in prior_records}
        current_by_id = {device.id: device for device in current_devices}
        findings: list[DriftFinding] = []

        for device in current_devices:
            previous = prior_by_id.get(device.id)
            if previous is None:
                severity = "warning" if device.risk_label in {"unknown", "watch"} or not device.known else "info"
                findings.append(
                    DriftFinding(
                        "new_device",
                        severity,
                        "New device",
                        f"{device.name} appeared at {device.ip}",
                        device.id,
                    )
                )
                continue

            if previous.ip and previous.ip != device.ip:
                findings.append(
                    DriftFinding(
                        "ip_changed",
                        "info",
                        "IP changed",
                        f"{device.name} moved from {previous.ip} to {device.ip}",
                        device.id,
                    )
                )

            if previous.known and not device.known:
                findings.append(
                    DriftFinding(
                        "profile_changed",
                        "warning",
                        "Known profile lost",
                        f"{device.name} was known before but is now unprofiled",
                        device.id,
                    )
                )

            if previous.device_type and previous.device_type != device.device_type:
                findings.append(
                    DriftFinding(
                        "type_changed",
                        "info",
                        "Type changed",
                        f"{device.name} changed from {previous.device_type} to {device.device_type}",
                        device.id,
                    )
                )

        for record in prior_records:
            if record.device_id in seen_ids:
                continue
            if not record.known and record.risk_label not in {"trusted", "watch"}:
                continue
            findings.append(
                DriftFinding(
                    "missing_device",
                    "warning" if record.known else "info",
                    "Missing device",
                    f"{record.name} was last seen at {record.last_seen or 'unknown time'}",
                    record.device_id,
                )
            )

        health_score = self._health_score(current_devices, findings)
        trust_score = self._trust_score(current_devices)
        drift_label = self._drift_label(findings)
        summary = self._summary(drift_label, findings)

        return NetworkMemory(
            health_score=health_score,
            trust_score=trust_score,
            drift_label=drift_label,
            summary=summary,
            findings=tuple(findings[:50]),
        )

    @staticmethod
    def _health_score(devices: list[Device], findings: list[DriftFinding]) -> int:
        score = 100
        score -= sum(12 for finding in findings if finding.severity == "warning")
        score -= sum(4 for finding in findings if finding.severity == "info")
        score -= sum(8 for device in devices if device.risk_label == "watch")
        return max(0, min(100, score))

    @staticmethod
    def _trust_score(devices: list[Device]) -> int:
        if not devices:
            return 100
        trusted = sum(1 for device in devices if device.known or device.risk_label == "trusted")
        return round(trusted / len(devices) * 100)

    @staticmethod
    def _drift_label(findings: list[DriftFinding]) -> str:
        warnings = sum(1 for finding in findings if finding.severity == "warning")
        if warnings >= 3:
            return "high"
        if warnings:
            return "medium"
        if findings:
            return "low"
        return "stable"

    @staticmethod
    def _summary(drift_label: str, findings: list[DriftFinding]) -> str:
        if drift_label == "stable":
            return "Network matches remembered baseline"
        warning_count = sum(1 for finding in findings if finding.severity == "warning")
        info_count = len(findings) - warning_count
        return f"{warning_count} warning drift events, {info_count} informational changes"
