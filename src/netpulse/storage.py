from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from .memory import DeviceMemoryRecord
from .models import Device, NetworkEvent


class HistoryStore:
    def __init__(self, path: Path, *, retention_days: int = 0) -> None:
        self.path = path
        self.retention_days = retention_days
        self.connection: sqlite3.Connection | None = None

    def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self._migrate()
        self.prune_history()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def record_snapshot(self, devices: Iterable[Device]) -> None:
        conn = self._conn()
        now = datetime.now().isoformat(timespec="seconds")
        for device in devices:
            conn.execute(
                """
                INSERT INTO devices (
                    device_id, mac, ip, name, vendor, device_type, risk_label,
                    first_seen, last_seen, known
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    mac=excluded.mac,
                    ip=excluded.ip,
                    name=excluded.name,
                    vendor=excluded.vendor,
                    device_type=excluded.device_type,
                    risk_label=excluded.risk_label,
                    last_seen=excluded.last_seen,
                    known=excluded.known
                """,
                (
                    device.id,
                    device.mac,
                    device.ip,
                    device.name,
                    device.vendor,
                    device.device_type,
                    device.risk_label,
                    device.first_seen.isoformat(timespec="seconds"),
                    device.last_seen.isoformat(timespec="seconds"),
                    int(device.known),
                ),
            )
            conn.execute(
                """
                INSERT INTO metrics (device_id, captured_at, online, latency_ms)
                VALUES (?, ?, ?, ?)
                """,
                (device.id, now, int(device.online), device.latency_ms),
            )
        conn.commit()

    def record_event(self, event: NetworkEvent, device_id: str | None = None) -> None:
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO events (captured_at, device_id, level, message)
            VALUES (?, ?, ?, ?)
            """,
            (
                event.timestamp.isoformat(timespec="seconds"),
                device_id,
                event.level,
                event.message,
            ),
        )
        conn.commit()

    def timeline(self, device_id: str, limit: int = 6) -> list[tuple[str, str, str]]:
        rows = self._conn().execute(
            """
            SELECT captured_at, level, message
            FROM events
            WHERE device_id = ? OR message LIKE ?
            ORDER BY captured_at DESC
            LIMIT ?
            """,
            (device_id, f"%{device_id}%", limit),
        ).fetchall()
        return [(str(row[0]), str(row[1]), str(row[2])) for row in rows]

    def recent_events(self, limit: int = 10) -> list[tuple[str, str, str, str]]:
        rows = self._conn().execute(
            """
            SELECT captured_at, COALESCE(device_id, ''), level, message
            FROM events
            ORDER BY captured_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [(str(row[0]), str(row[1]), str(row[2]), str(row[3])) for row in rows]

    def latency_summary(self, limit: int = 10) -> list[tuple[str, int, float | None, float | None]]:
        rows = self._conn().execute(
            """
            SELECT device_id,
                   COUNT(latency_ms) AS samples,
                   AVG(latency_ms) AS avg_latency,
                   MAX(latency_ms) AS max_latency
            FROM metrics
            WHERE latency_ms IS NOT NULL
            GROUP BY device_id
            ORDER BY avg_latency DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            (
                str(row[0]),
                int(row[1] or 0),
                float(row[2]) if row[2] is not None else None,
                float(row[3]) if row[3] is not None else None,
            )
            for row in rows
        ]

    def save_baseline(self, records: Iterable[DeviceMemoryRecord]) -> int:
        conn = self._conn()
        approved_at = datetime.now().isoformat(timespec="seconds")
        rows = list(records)
        with conn:
            conn.execute("DELETE FROM baseline_devices")
            for record in rows:
                conn.execute(
                    """
                    INSERT INTO baseline_devices (
                        device_id, mac, ip, name, vendor, device_type,
                        risk_label, first_seen, last_seen, known, approved_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.device_id,
                        record.mac,
                        record.ip,
                        record.name,
                        record.vendor,
                        record.device_type,
                        record.risk_label,
                        record.first_seen,
                        record.last_seen,
                        int(record.known),
                        approved_at,
                    ),
                )
        return len(rows)

    def baseline_records(self) -> list[DeviceMemoryRecord]:
        rows = self._conn().execute(
            """
            SELECT device_id, mac, ip, name, vendor, device_type, risk_label,
                   first_seen, last_seen, known
            FROM baseline_devices
            ORDER BY name ASC, ip ASC
            """
        ).fetchall()
        return [self._device_memory_record(row) for row in rows]

    def baseline_saved_at(self) -> str | None:
        row = self._conn().execute(
            "SELECT MAX(approved_at) FROM baseline_devices"
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return str(row[0])

    def clear_baseline(self) -> int:
        conn = self._conn()
        with conn:
            cursor = conn.execute("DELETE FROM baseline_devices")
        return int(cursor.rowcount)

    def device_records(self) -> list[DeviceMemoryRecord]:
        rows = self._conn().execute(
            """
            SELECT device_id, mac, ip, name, vendor, device_type, risk_label,
                   first_seen, last_seen, known
            FROM devices
            ORDER BY last_seen DESC, name ASC
            """
        ).fetchall()
        return [self._device_memory_record(row) for row in rows]

    def prune_history(self) -> None:
        if self.retention_days <= 0:
            return
        cutoff = (datetime.now() - timedelta(days=self.retention_days)).isoformat(timespec="seconds")
        conn = self._conn()
        conn.execute("DELETE FROM metrics WHERE captured_at < ?", (cutoff,))
        conn.execute("DELETE FROM events WHERE captured_at < ?", (cutoff,))
        conn.commit()

    def _migrate(self) -> None:
        conn = self._conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                mac TEXT,
                ip TEXT,
                name TEXT,
                vendor TEXT,
                device_type TEXT,
                risk_label TEXT,
                first_seen TEXT,
                last_seen TEXT,
                known INTEGER
            );

            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                online INTEGER NOT NULL,
                latency_ms REAL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                device_id TEXT,
                level TEXT NOT NULL,
                message TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_metrics_device_time
                ON metrics(device_id, captured_at);
            CREATE INDEX IF NOT EXISTS idx_events_device_time
                ON events(device_id, captured_at);

            CREATE TABLE IF NOT EXISTS baseline_devices (
                device_id TEXT PRIMARY KEY,
                mac TEXT,
                ip TEXT,
                name TEXT,
                vendor TEXT,
                device_type TEXT,
                risk_label TEXT,
                first_seen TEXT,
                last_seen TEXT,
                known INTEGER,
                approved_at TEXT NOT NULL
            );
            """
        )
        conn.commit()

    def _conn(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("HistoryStore is not connected")
        return self.connection

    @staticmethod
    def _device_memory_record(row: sqlite3.Row | tuple) -> DeviceMemoryRecord:
        return DeviceMemoryRecord(
            device_id=str(row[0]),
            mac=str(row[1] or ""),
            ip=str(row[2] or ""),
            name=str(row[3] or "Unknown device"),
            vendor=str(row[4] or "Unknown vendor"),
            device_type=str(row[5] or "host"),
            risk_label=str(row[6] or "unknown"),
            first_seen=str(row[7] or ""),
            last_seen=str(row[8] or ""),
            known=bool(row[9]),
        )
