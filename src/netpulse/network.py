from __future__ import annotations

import asyncio
import ipaddress
import platform
import re
import socket
import subprocess
import time
from collections.abc import AsyncIterator, Iterable
from itertools import islice

from .models import ScanResult
from .state import NetworkState

ARP_LINE = re.compile(
    r"(?P<ip>\d+\.\d+\.\d+\.\d+).*?"
    r"(?P<mac>(?:[0-9a-fA-F]{1,2}[:-]){5}[0-9a-fA-F]{1,2})"
)

MAX_SCAN_HOSTS = 4096


class NetworkEngine:
    def __init__(
        self,
        cidr: str,
        interval: float = 5.0,
        concurrency: int = 64,
        timeout: float = 1.0,
        deep_scan: bool = False,
        resolve_names: bool = False,
    ) -> None:
        self.network = ipaddress.ip_network(cidr, strict=False)
        self.interval = interval
        self.concurrency = concurrency
        self.timeout = timeout
        self.deep_scan = deep_scan
        self.resolve_names = resolve_names
        self.gateway_ip = self._detect_gateway_ip() or self._estimate_gateway_ip()
        self.host_count = self._estimate_host_count()

    async def watch(self, state: NetworkState) -> AsyncIterator[None]:
        while True:
            state.scanning = True
            try:
                results = await self.scan_once()
                state.apply_scan_results(results)
            finally:
                state.scanning = False
            yield
            await asyncio.sleep(self.interval)

    async def scan_once(self) -> list[ScanResult]:
        macs_by_ip = await self._read_arp_table()
        targets = self._scan_targets(macs_by_ip)

        results: list[ScanResult | None] = []
        target_iterator = iter(targets)
        while batch := tuple(islice(target_iterator, self.concurrency)):
            results.extend(
                await asyncio.gather(*(self._ping_host(str(ip)) for ip in batch))
            )

        enriched: list[ScanResult] = []
        seen_ips: set[str] = set()
        for result in results:
            if result is None:
                continue
            seen_ips.add(result.ip)
            mac = macs_by_ip.get(result.ip, result.mac)
            enriched.append(ScanResult(result.ip, mac, result.latency_ms, result.hostname))

        # Many local devices ignore ICMP. ARP still tells us they are present,
        # so use the ARP cache as a first-class discovery source.
        for ip, mac in macs_by_ip.items():
            if ip in seen_ips or ipaddress.ip_address(ip) not in self.network:
                continue
            enriched.append(ScanResult(ip=ip, mac=mac, latency_ms=None, hostname=None))

        return enriched

    async def arp_snapshot(self) -> list[ScanResult]:
        macs_by_ip = await self._read_arp_table()
        return [
            ScanResult(ip=ip, mac=mac, latency_ms=None, hostname=None)
            for ip, mac in sorted(macs_by_ip.items())
            if ipaddress.ip_address(ip) in self.network
        ]

    def _scan_targets(
        self, macs_by_ip: dict[str, str]
    ) -> Iterable[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        if self.deep_scan or not macs_by_ip:
            if self.host_count > MAX_SCAN_HOSTS:
                reason = "deep scan" if self.deep_scan else "empty ARP fallback"
                raise ValueError(
                    f"{reason} requires scanning {self.host_count} hosts; "
                    f"maximum is {MAX_SCAN_HOSTS}"
                )
            return self.network.hosts()

        targets = {
            ipaddress.ip_address(ip)
            for ip in macs_by_ip
            if ipaddress.ip_address(ip) in self.network
        }
        if self.gateway_ip:
            gateway = ipaddress.ip_address(self.gateway_ip)
            if gateway in self.network:
                targets.add(gateway)
        return sorted(targets)

    async def _ping_host(self, ip: str) -> ScanResult | None:
        command = self._ping_command(ip, platform.system().lower())

        started = time.perf_counter()
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            return_code = await asyncio.wait_for(process.wait(), timeout=self.timeout + 0.5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return None

        if return_code != 0:
            return None

        latency_ms = (time.perf_counter() - started) * 1000
        hostname = await asyncio.to_thread(self._resolve_hostname, ip) if self.resolve_names else None
        return ScanResult(ip=ip, mac="", latency_ms=latency_ms, hostname=hostname)

    def _ping_command(self, ip: str, system: str) -> list[str]:
        timeout_ms = max(1, int(self.timeout * 1000))
        if "windows" in system:
            return ["ping", "-n", "1", "-w", str(timeout_ms), ip]
        if "darwin" in system:
            return ["ping", "-c", "1", "-W", str(timeout_ms), ip]
        return ["ping", "-c", "1", "-W", str(max(1, int(self.timeout))), ip]

    async def _read_arp_table(self) -> dict[str, str]:
        text = await asyncio.to_thread(self._read_arp_table_sync)
        return self._parse_arp_table(text)

    @staticmethod
    def _parse_arp_table(text: str) -> dict[str, str]:
        return {
            match.group("ip"): _normalize_mac(match.group("mac"))
            for match in ARP_LINE.finditer(text)
        }

    @staticmethod
    def _read_arp_table_sync() -> str:
        try:
            completed = subprocess.run(
                ["arp", "-a"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return completed.stdout

    @staticmethod
    def _resolve_hostname(ip: str) -> str | None:
        try:
            return socket.gethostbyaddr(ip)[0]
        except socket.herror:
            return None

    def _estimate_gateway_ip(self) -> str | None:
        hosts = iter(self.network.hosts())
        try:
            return str(next(hosts))
        except StopIteration:
            return None

    def _estimate_host_count(self) -> int:
        if self.network.num_addresses <= 2:
            return self.network.num_addresses
        return self.network.num_addresses - 2

    def _detect_gateway_ip(self) -> str | None:
        command = self._gateway_command(platform.system().lower())
        if command is None:
            return None
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        for candidate in self._gateway_candidates(completed.stdout):
            if self._ip_in_network(candidate):
                return candidate
        return None

    @staticmethod
    def _gateway_command(system: str) -> list[str] | None:
        if "windows" in system:
            return ["route", "print", "-4", "0.0.0.0"]
        if "darwin" in system:
            return ["route", "-n", "get", "default"]
        if "linux" in system:
            return ["ip", "route", "show", "default"]
        return None

    @staticmethod
    def _gateway_candidates(text: str) -> list[str]:
        candidates: list[str] = []
        candidates.extend(
            re.findall(
                r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)",
                text,
                flags=re.MULTILINE,
            )
        )
        candidates.extend(re.findall(r"\bgateway:\s*(\d+\.\d+\.\d+\.\d+)", text))
        candidates.extend(re.findall(r"\bdefault\s+via\s+(\d+\.\d+\.\d+\.\d+)", text))
        return candidates

    def _ip_in_network(self, ip: str) -> bool:
        try:
            return ipaddress.ip_address(ip) in self.network
        except ValueError:
            return False


def _normalize_mac(mac: str) -> str:
    parts = mac.replace("-", ":").lower().split(":")
    return ":".join(part.zfill(2) for part in parts)
