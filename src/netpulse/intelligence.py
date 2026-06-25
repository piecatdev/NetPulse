from __future__ import annotations

from ipaddress import ip_address

from .models import ScanResult


OUI_VENDORS = {
    "00:1a:2b": "Cisco",
    "00:1b:63": "Apple",
    "00:1c:b3": "Apple",
    "3c:22:fb": "Apple",
    "f0:18:98": "Apple",
    "dc:a6:32": "Raspberry Pi",
    "b8:27:eb": "Raspberry Pi",
    "e4:5f:01": "Raspberry Pi",
    "00:11:32": "Synology",
    "24:5e:be": "QNAP",
    "00:09:34": "Dell",
    "3c:97:0e": "Wistron",
    "70:85:c2": "ASUSTek",
    "f4:f5:d8": "Google",
    "d8:3a:dd": "Google",
    "bc:92:6b": "Samsung",
    "fc:8f:90": "Samsung",
    "a4:77:33": "Google Nest",
    "44:65:0d": "Amazon",
    "fc:a1:83": "Amazon",
    "24:0a:c4": "Espressif",
    "30:ae:a4": "Espressif",
    "84:f3:eb": "Espressif",
}

GATEWAY_HINTS = ("router", "gateway", "fritz", "openwrt", "tplink", "deco", "eero")
STORAGE_HINTS = ("nas", "synology", "qnap", "truenas", "storage")
PRINTER_HINTS = ("printer", "print", "hp-", "brother", "canon", "epson", "laserjet")
CAMERA_HINTS = ("camera", "cam", "ipcam", "webcam", "reolink", "arlo", "hikvision")
MOBILE_HINTS = ("iphone", "ipad", "android", "phone", "pixel", "galaxy")
IOT_HINTS = (
    "tv",
    "chromecast",
    "nest",
    "alexa",
    "echo",
    "speaker",
    "homepod",
    "sensor",
    "esp",
    "plug",
    "bulb",
)


class DeviceIntelligence:
    def classify(
        self,
        result: ScanResult,
        *,
        known: bool,
        gateway_ip: str | None = None,
    ) -> tuple[str, str, str, int, str, tuple[str, ...]]:
        vendor = self.vendor_for(result.mac)
        device_type = self.device_type_for(result, vendor, gateway_ip)
        risk_label, risk_score = self.risk_for(result, known, device_type, vendor)
        signals = self.identity_signals(result, known, vendor, device_type, gateway_ip)
        confidence = self.confidence_for(signals)
        return vendor, device_type, risk_label, risk_score, confidence, signals

    @staticmethod
    def vendor_for(mac: str) -> str:
        if not mac:
            return "Unknown vendor"
        normalized = mac.replace("-", ":").lower()
        return OUI_VENDORS.get(normalized[:8], "Unknown vendor")

    @staticmethod
    def device_type_for(result: ScanResult, vendor: str, gateway_ip: str | None) -> str:
        hostname = (result.hostname or "").lower()
        if gateway_ip and result.ip == gateway_ip:
            return "gateway"
        if any(token in hostname for token in GATEWAY_HINTS):
            return "gateway"
        if any(token in hostname for token in STORAGE_HINTS):
            return "storage"
        if any(token in hostname for token in PRINTER_HINTS):
            return "printer"
        if any(token in hostname for token in CAMERA_HINTS):
            return "camera"
        if any(token in hostname for token in MOBILE_HINTS):
            return "mobile"
        if any(token in hostname for token in IOT_HINTS):
            return "iot"
        if vendor in {"Synology", "QNAP"}:
            return "storage"
        if vendor in {"Google Nest", "Amazon", "Espressif"}:
            return "iot"
        return "host"

    @staticmethod
    def risk_for(
        result: ScanResult,
        known: bool,
        device_type: str,
        vendor: str,
    ) -> tuple[str, int]:
        if device_type == "gateway":
            return "trusted", 5
        if known:
            return "trusted", 15
        score = 55
        if vendor == "Unknown vendor":
            score += 20
        if not result.mac:
            score += 10
        if _is_link_local(result.ip):
            score += 10
        if score >= 75:
            return "watch", score
        return "unknown", score

    @staticmethod
    def identity_signals(
        result: ScanResult,
        known: bool,
        vendor: str,
        device_type: str,
        gateway_ip: str | None,
    ) -> tuple[str, ...]:
        signals: list[str] = []
        if known:
            signals.append("saved name")
        if result.hostname:
            signals.append("hostname")
        if vendor != "Unknown vendor":
            signals.append("mac vendor")
        if gateway_ip and result.ip == gateway_ip:
            signals.append("gateway ip")
        elif device_type != "host":
            signals.append("type hint")
        if result.mac:
            signals.append("mac address")
        return tuple(signals)

    @staticmethod
    def confidence_for(signals: tuple[str, ...]) -> str:
        if "gateway ip" in signals:
            return "high"
        strong = {"saved name", "gateway ip", "hostname"}
        score = len(signals) + sum(1 for signal in signals if signal in strong)
        if score >= 5:
            return "high"
        if score >= 3:
            return "medium"
        return "low"


def _is_link_local(ip: str) -> bool:
    try:
        return ip_address(ip).is_link_local
    except ValueError:
        return False
