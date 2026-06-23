from __future__ import annotations

from datetime import datetime

from rich.align import Align
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from .models import Device
from .state import NetworkState


ACCENT = "#00d7ff"
PULSE = "#5cff9d"
WARNING = "#ffb000"
DANGER = "#ff4d6d"
MUTED = "grey58"
SURFACE = "#101820"
TEXT = "#d7f7ff"


class Dashboard:
    def __init__(
        self,
        state: NetworkState,
        refresh_per_second: int = 2,
        alt_screen: bool = False,
        line_input: bool = False,
        auto_refresh: bool = False,
    ) -> None:
        self.state = state
        self.refresh_per_second = refresh_per_second
        self.alt_screen = alt_screen
        self.line_input = line_input
        self.auto_refresh = auto_refresh

    def live(self) -> Live:
        return Live(
            self.render(),
            get_renderable=self.render,
            refresh_per_second=self.refresh_per_second,
            auto_refresh=self.auto_refresh,
            screen=self.alt_screen,
            transient=False,
        )

    def render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=4),
            Layout(name="main", ratio=3),
            Layout(name="footer", size=10),
        )
        layout["header"].update(self._render_header())
        layout["main"].split_row(
            Layout(self._render_primary_view(), name="primary", ratio=3),
            Layout(self._render_details(), name="details", size=38),
        )
        layout["footer"].update(self._render_events())
        return layout

    def _render_header(self) -> Panel:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total = len(self.state.devices)
        online = sum(1 for device in self.state.devices.values() if device.online)
        unknown = sum(1 for device in self.state.devices.values() if not device.known)
        status = f"[bold {WARNING}]scanning[/]" if self.state.scanning else f"[bold {PULSE}]idle[/]"
        last_scan = (
            self.state.last_scan_at.strftime("%H:%M:%S")
            if self.state.last_scan_at
            else "never"
        )

        header = Table.grid(expand=True)
        header.add_column(justify="left")
        header.add_column(justify="center")
        header.add_column(justify="right")
        header.add_row(
            f"[bold {ACCENT}]NETPULSE[/] [dim]// local signal surface[/] [dim]{now}[/]",
            f"[{MUTED}]state[/] {status} [{MUTED}]last[/] {last_scan} [{MUTED}]scan[/] {self.state.last_scan_count} [{MUTED}]view[/] [bold {ACCENT}]{self.state.view_mode}[/]",
            f"[bold {PULSE}]{online}/{total}[/] [{MUTED}]online[/] [bold {WARNING}]{unknown} unknown[/]",
        )
        return Panel(header, border_style=ACCENT, style=TEXT)

    def _render_primary_view(self) -> Panel:
        if self.state.view_mode == "map":
            return self._render_network_map()
        if self.state.view_mode == "table":
            return self._render_device_table()
        if self.state.view_mode == "memory":
            return self._render_network_memory()
        return self._render_devices()

    def _render_devices(self) -> Panel:
        devices, page, total_pages = self.state.visible_devices(page_size=6)
        if not devices:
            empty = Align.center(
                Text("No devices detected. Waiting for the first scan...", style="dim"),
                vertical="middle",
            )
            return Panel(empty, title="Devices", border_style=ACCENT)

        grid = Table.grid(expand=True)
        columns = 3
        for _ in range(columns):
            grid.add_column(ratio=1)

        cards = [
            self._device_card(device, selected=device.id == self.state.selected_device_id)
            for device in devices
        ]
        for index in range(0, len(cards), columns):
            row = cards[index : index + columns]
            grid.add_row(*row, *[""] * (columns - len(row)))

        return Panel(
            grid,
            title=f"[bold {ACCENT}]Device Cards[/] [{MUTED}]page {page}/{total_pages}[/]",
            border_style=ACCENT,
        )

    def _render_device_table(self) -> Panel:
        devices, page, total_pages = self.state.visible_devices(page_size=14)
        table = Table(expand=True)
        table.add_column("", width=2)
        table.add_column("Name", no_wrap=True)
        table.add_column("IP", no_wrap=True)
        table.add_column("Type", no_wrap=True)
        table.add_column("Vendor", no_wrap=True)
        table.add_column("Risk", no_wrap=True)
        table.add_column("Latency", justify="right")

        for device in devices:
            selected = ">" if device.id == self.state.selected_device_id else ""
            status_style = PULSE if device.online else DANGER
            risk_style = self._risk_style(device)
            table.add_row(
                f"[{WARNING}]{selected}[/]",
                f"[{status_style}]{device.name}[/]",
                f"[{MUTED}]{device.ip}[/]",
                device.device_type,
                f"[{MUTED}]{device.vendor}[/]",
                f"[{risk_style}]{device.risk_label}[/]",
                self._latency_label(device),
            )

        if not devices:
            table.add_row("", "[dim]No devices detected[/]", "", "", "", "", "")

        total = len(self.state.devices)
        return Panel(
            table,
            title=f"[bold {ACCENT}]Signal Table[/] [{MUTED}]{page}/{total_pages} ({total} total)[/]",
            border_style=ACCENT,
        )

    def _render_network_memory(self) -> Panel:
        memory = self.state.network_memory
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        table.add_column(ratio=1)

        health_style = self._score_style(memory.health_score)
        trust_style = self._score_style(memory.trust_score)
        drift_style = {
            "stable": PULSE,
            "learning": ACCENT,
            "low": ACCENT,
            "medium": WARNING,
            "high": DANGER,
        }.get(memory.drift_label, TEXT)

        table.add_row(
            f"[bold {health_style}]HEALTH {memory.health_score:>3}/100[/]",
            f"[bold {trust_style}]TRUST {memory.trust_score:>3}/100[/]",
            f"[bold {drift_style}]DRIFT {memory.drift_label.upper()}[/]",
        )
        table.add_row("", "", "")
        table.add_row(f"[{TEXT}]{memory.summary}[/]", "", "")
        table.add_row("", "", "")

        findings = Table(expand=True)
        findings.add_column("Severity", width=9)
        findings.add_column("Signal", width=18)
        findings.add_column("Detail")

        visible_findings, page, total_pages = self.state.visible_memory_findings(page_size=7)

        if visible_findings:
            for index, finding in enumerate(visible_findings, start=self.state.memory_scroll_offset + 1):
                style = {
                    "warning": WARNING,
                    "error": DANGER,
                    "info": ACCENT,
                }.get(finding.severity, TEXT)
                findings.add_row(
                    f"[{style}]{finding.severity.upper()}[/]",
                    f"{index:02d} {finding.title}",
                    Text(self._clip(finding.detail, 82), style=TEXT, overflow="ellipsis"),
                )
        else:
            findings.add_row(f"[{PULSE}]OK[/]", "Stable baseline", "No remembered drift detected")

        content = Table.grid(expand=True)
        content.add_row(table)
        content.add_row(findings)

        return Panel(
            content,
            title=f"[bold {ACCENT}]Network Memory[/]",
            subtitle=f"[{MUTED}]up/down scroll findings | page {page}/{total_pages} | local baseline comparison[/]",
            border_style=drift_style,
        )

    def _render_network_map(self) -> Panel:
        devices = self.state.sorted_devices()
        gateway_ip = self.state.gateway_ip or "gateway stimato"
        selected = self.state.selected_device()
        graph = Text(no_wrap=False, overflow="fold")
        visible, page, total_pages = self._map_visible_devices(devices, page_size=12)
        left_nodes = visible[:6]
        right_nodes = visible[6:12]
        online = sum(1 for device in devices if device.online)
        watch = sum(1 for device in devices if device.risk_label in {"unknown", "watch"})

        self._append_map_line(graph, "              _   _ _____ _____ ____  _   _ _     ____  _____", ACCENT)
        self._append_map_line(graph, "             | \\ | | ____|_   _|  _ \\| | | | |   / ___|| ____|", ACCENT)
        self._append_map_line(graph, "             |  \\| |  _|   | | | |_) | | | | |   \\___ \\|  _|", ACCENT)
        self._append_map_line(graph, "             | |\\  | |___  | | |  __/| |_| | |___ ___) | |___", ACCENT)
        self._append_map_line(graph, "             |_| \\_|_____| |_| |_|    \\___/|_____|____/|_____|", ACCENT)
        self._append_map_line(graph, "", MUTED)
        self._append_map_line(graph, "        .--------------------------- WAN ---------------------------.", MUTED)
        self._append_map_line(graph, f"        | uplink -> gateway {gateway_ip:<15} -> LAN signal core     |", PULSE)
        self._append_map_line(graph, "        '-----------------------------+-----------------------------'", MUTED)
        self._append_map_line(graph, "                                      |", MUTED)
        self._append_map_line(graph, "                         .------------+------------.", MUTED)
        self._append_map_line(graph, "                         |      NETPULSE CORE      |", ACCENT)
        self._append_map_line(graph, f"                         | online {online:<3} watch {watch:<3} page {page}/{total_pages:<2} |", TEXT)
        self._append_map_line(graph, "                         '------------+------------'", MUTED)
        self._append_map_line(graph, "                         /                         \\", MUTED)
        self._append_map_line(graph, "                CORE / KNOWN                 WATCH / UNKNOWN", MUTED)
        self._append_map_line(graph, "              .--------------.             .--------------.", MUTED)

        max_rows = max(len(left_nodes), len(right_nodes), 1)
        for index in range(max_rows):
            left = self._map_node_chip(left_nodes[index]) if index < len(left_nodes) else " " * 30
            right = self._map_node_chip(right_nodes[index]) if index < len(right_nodes) else ""
            left_style = self._node_style(left_nodes[index]) if index < len(left_nodes) else MUTED
            right_style = self._node_style(right_nodes[index]) if index < len(right_nodes) else MUTED
            graph.append("        ")
            graph.append(left, style=left_style)
            graph.append("  ==== core ====  ", style=MUTED)
            graph.append(right, style=right_style)
            graph.append("\n")

        self._append_map_line(graph, "              '--------------'             '--------------'", MUTED)
        self._append_map_line(graph, "", MUTED)
        self._append_map_line(graph, self._map_distribution_line(devices), ACCENT)

        if selected is not None:
            self._append_map_line(graph, "", MUTED)
            self._append_map_line(graph, "       .---------------- SELECTED NODE ----------------.", WARNING)
            self._append_map_line(
                graph,
                f"       | {selected.ip:<15} {selected.name[:26]:<26} |",
                TEXT,
            )
            self._append_map_line(
                graph,
                f"       | type={selected.device_type:<8} risk={selected.risk_label:<8} latency={self._plain_latency(selected):<8} |",
                self._risk_style(selected),
            )
            self._append_map_line(graph, "       '------------------------------------------------'", WARNING)

        return Panel(
            graph,
            title=f"[bold {ACCENT}]NetPulse Signal Map[/]",
            subtitle=f"[{MUTED}]arrows/HJKL navigate nodes | R rescans | page follows selection | estimated graph[/]",
            border_style=ACCENT,
        )

    def _device_card(self, device: Device, selected: bool = False) -> Panel:
        status_text = "ON" if device.online else "OFF"
        status_style = f"bold {PULSE}" if device.online else f"bold {DANGER}"
        latency = device.latency_ms if device.latency_ms is not None else 0
        activity = self._latency_activity(latency, device.online)
        known_badge = f"[{MUTED}]known[/]" if device.known else f"[bold {WARNING}]UNKNOWN[/]"

        table = Table.grid(padding=(0, 1))
        table.add_column(ratio=1)
        table.add_column(justify="right")
        table.add_row(f"[bold]{device.name}[/]", f"[{status_style}]{status_text}[/]")
        table.add_row(f"[dim]{device.ip}[/]", self._latency_label(device))
        table.add_row("[dim]MAC[/]", f"[dim]{device.mac or 'unknown'}[/]")
        table.add_row("[dim]Profile[/]", known_badge)
        table.add_row("[dim]Type[/]", device.device_type)
        table.add_row("[dim]Risk[/]", f"[{self._risk_style(device)}]{device.risk_label}[/]")
        table.add_row("[dim]Activity[/]", activity)

        border = WARNING if selected else (PULSE if device.online else DANGER)
        title = f"[bold {WARNING}]selected[/]" if selected else ""
        return Panel(table, title=title, border_style=border, padding=(1, 1))

    @staticmethod
    def _latency_label(device: Device) -> str:
        if not device.online:
            return f"[{DANGER}]offline[/]"
        if device.latency_ms is None:
            return f"[{MUTED}]n/d[/]"
        return f"[bold {PULSE}]{device.latency_ms:.0f} ms[/]"

    @staticmethod
    def _latency_activity(latency_ms: float, online: bool) -> ProgressBar:
        if not online:
            return ProgressBar(total=100, completed=0, width=18, pulse=False)
        completed = max(5, min(100, int(100 - latency_ms / 3)))
        return ProgressBar(total=100, completed=completed, width=18, pulse=latency_ms > 250)

    def _render_details(self) -> Panel:
        device = self.state.selected_device()
        if device is None:
            return Panel(
                Align.center(Text("Seleziona un dispositivo", style="dim"), vertical="middle"),
                title="Detail",
                border_style=MUTED,
            )

        table = Table.grid(padding=(0, 1))
        table.add_column(ratio=1)
        table.add_column(justify="right")
        table.add_row("[bold]Name[/]", f"[bold]{device.name}[/]")
        table.add_row("[dim]IP[/]", device.ip)
        table.add_row("[dim]MAC[/]", device.mac or "unknown")
        table.add_row("[dim]Vendor[/]", device.vendor)
        table.add_row("[dim]Type[/]", device.device_type)
        table.add_row("[dim]State[/]", f"[{PULSE}]online[/]" if device.online else f"[{DANGER}]offline[/]")
        table.add_row("[dim]Profile[/]", f"[{PULSE}]known[/]" if device.known else f"[{WARNING}]unknown[/]")
        table.add_row("[dim]Risk[/]", f"[{self._risk_style(device)}]{device.risk_label} ({device.risk_score})[/]")
        table.add_row("[dim]Latency[/]", self._latency_label(device))
        table.add_row("[dim]Trend[/]", self.state.latency_trend(device.id))
        table.add_row("[dim]Last seen[/]", device.last_seen.strftime("%H:%M:%S"))

        timeline = Table.grid()
        timeline.add_row("")
        timeline.add_row("[bold]Timeline[/]")
        for captured_at, level, message in self.state.selected_timeline(limit=5):
            style = {
                "success": "green",
                "warning": "yellow",
                "error": "red",
            }.get(level, "dim")
            time_label = captured_at.split("T")[-1] if "T" in captured_at else captured_at[-8:]
            timeline.add_row(f"[dim]{time_label}[/] [{style}]{message}[/]")
        if not self.state.selected_timeline(limit=1):
            timeline.add_row("[dim]No timeline events for this device[/]")

        hint = Table.grid()
        hint.add_row("")
        hint.add_row("[dim]Rename:[/]")
        hint.add_row("[bold]netpulse-rename <mac> <name>[/]")

        content = Table.grid(expand=True)
        content.add_row(table)
        content.add_row(timeline)
        content.add_row(hint)

        border = PULSE if device.known else WARNING
        return Panel(content, title=f"[bold {ACCENT}]Node Detail[/]", border_style=border)

    def _render_events(self) -> Panel:
        table = Table.grid(expand=True)
        table.add_column("time", width=10)
        table.add_column("event")

        rows_added = 0
        for event in list(self.state.events)[:7]:
            style = {
                "success": PULSE,
                "warning": WARNING,
                "error": DANGER,
            }.get(event.level, MUTED)
            table.add_row(
                f"[dim]{event.timestamp.strftime('%H:%M:%S')}[/]",
                Text(self._clip(event.message, 96), style=style, no_wrap=True, overflow="ellipsis"),
            )
            rows_added += 1

        if self.state.persistence_error and rows_added < 7:
            table.add_row(
                "[dim]storage[/]",
                Text(
                    self._clip(f"History unavailable: {self.state.persistence_error}", 96),
                    style=WARNING,
                    no_wrap=True,
                    overflow="ellipsis",
                ),
            )
            rows_added += 1

        if rows_added == 0:
            table.add_row("[dim]--:--:--[/]", Text("No events recorded", style=MUTED))
            rows_added += 1

        while rows_added < 7:
            table.add_row("[dim]        [/]", Text(" ", style=MUTED))
            rows_added += 1

        return Panel(
            table,
            title=f"[bold {ACCENT}]Signal Log[/]",
            subtitle=f"[dim]{self._controls_hint()} | last: {self.state.last_action}[/]",
            border_style=ACCENT,
        )

    def _controls_hint(self) -> str:
        if self.line_input:
            return "commands + Enter: j/k navigate | v view | r refresh | q quit"
        return "Arrows/HJKL navigate | V view | R refresh | Q quit"

    @staticmethod
    def _score_style(score: int) -> str:
        if score >= 85:
            return PULSE
        if score >= 65:
            return WARNING
        return DANGER

    @staticmethod
    def _risk_style(device: Device) -> str:
        if device.risk_label == "trusted":
            return PULSE
        if device.risk_label == "watch":
            return WARNING
        return WARNING

    @staticmethod
    def _bar(count: int, width: int = 12) -> str:
        filled = min(width, count)
        return "[" + ("#" * filled).ljust(width, ".") + "]"

    def _graph_device_lines(
        self,
        devices: list[Device],
        prefix: str = "       |   ",
        limit: int = 8,
    ) -> list[str]:
        lines: list[str] = []
        for index, device in enumerate(devices[:limit]):
            connector = "`--" if index == min(len(devices), limit) - 1 else "+--"
            selected = ">" if device.id == self.state.selected_device_id else " "
            status = "x" if not device.online else ("!" if device.risk_label in {"unknown", "watch"} else "-")
            latency = self._plain_latency(device)
            lines.append(
                f"{prefix}{connector} {selected}{status} {device.ip:<15} {device.name} ({latency})"
            )
        remaining = len(devices) - limit
        if remaining > 0:
            lines.append(f"{prefix}`-- ... {remaining} more nodes")
        return lines

    @staticmethod
    def _online_count(devices: list[Device]) -> int:
        return sum(1 for device in devices if device.online)

    @staticmethod
    def _plain_latency(device: Device) -> str:
        if not device.online:
            return "offline"
        if device.latency_ms is None:
            return "n/d"
        return f"{device.latency_ms:.0f}ms"

    @staticmethod
    def _append_map_line(text: Text, line: str, style: str) -> None:
        text.append(line, style=style)
        text.append("\n")

    def _append_group_nodes(
        self,
        graph: Text,
        devices: list[Device],
        prefix: str,
        limit: int = 7,
    ) -> None:
        visible = devices[:limit]
        for index, device in enumerate(visible):
            connector = "`--" if index == len(visible) - 1 and len(devices) <= limit else "+--"
            marker = ">" if device.id == self.state.selected_device_id else " "
            signal = "x" if not device.online else ("!" if device.risk_label in {"unknown", "watch"} else "-")
            line = (
                f"{prefix}{connector} [{marker}{signal}] "
                f"{device.ip:<15} {self._short_name(device):<22} "
                f"{self._plain_latency(device):>7}"
            )
            graph.append(line, style=self._node_style(device))
            graph.append("\n")
        remaining = len(devices) - limit
        if remaining > 0:
            self._append_map_line(graph, f"{prefix}`-- [... ] {remaining} hidden nodes", MUTED)

    @staticmethod
    def _short_name(device: Device, width: int = 22) -> str:
        name = device.name.replace("\n", " ")
        if len(name) <= width:
            return name
        return name[: width - 1] + "~"

    @staticmethod
    def _group_style(label: str) -> str:
        return {
            "gateways": PULSE,
            "storage": ACCENT,
            "mobile": "#7df9ff",
            "iot": WARNING,
            "hosts": TEXT,
        }.get(label, TEXT)

    def _node_style(self, device: Device) -> str:
        if not device.online:
            return DANGER
        if device.id == self.state.selected_device_id:
            return f"bold {WARNING}"
        if device.risk_label == "trusted":
            return PULSE
        if device.risk_label == "watch":
            return WARNING
        return TEXT

    @staticmethod
    def _clip(value: str, width: int) -> str:
        single_line = value.replace("\n", " ")
        if len(single_line) <= width:
            return single_line
        return single_line[: max(0, width - 1)] + "~"

    def _map_node_chip(self, device: Device) -> str:
        marker = ">" if device.id == self.state.selected_device_id else " "
        signal = "x" if not device.online else ("!" if device.risk_label in {"unknown", "watch"} else "-")
        type_code = {
            "gateway": "GW",
            "storage": "ST",
            "mobile": "MO",
            "iot": "IO",
            "host": "HO",
        }.get(device.device_type, "??")
        return f"[{marker}{signal}] {device.ip:<13} {type_code} {self._plain_latency(device):>4}"

    def _map_distribution_line(self, devices: list[Device]) -> str:
        counts = {
            "GW": sum(1 for device in devices if device.device_type == "gateway"),
            "ST": sum(1 for device in devices if device.device_type == "storage"),
            "MO": sum(1 for device in devices if device.device_type == "mobile"),
            "IO": sum(1 for device in devices if device.device_type == "iot"),
            "HO": sum(1 for device in devices if device.device_type == "host"),
        }
        bars = "  ".join(f"{label}:{self._bar(count, width=8)} {count}" for label, count in counts.items())
        return f"        distribution  {bars}"

    def _map_visible_devices(self, devices: list[Device], page_size: int) -> tuple[list[Device], int, int]:
        ordered = self._map_ordered_devices(devices)
        if not ordered:
            return [], 0, 0
        ids = [device.id for device in ordered]
        selected_index = ids.index(self.state.selected_device_id) if self.state.selected_device_id in ids else 0
        page = selected_index // page_size
        start = page * page_size
        total_pages = (len(ordered) + page_size - 1) // page_size
        return ordered[start : start + page_size], page + 1, total_pages

    @staticmethod
    def _map_ordered_devices(devices: list[Device]) -> list[Device]:
        def weight(device: Device) -> tuple[int, int, str]:
            type_weight = {
                "gateway": 0,
                "storage": 1,
                "host": 2,
                "mobile": 3,
                "iot": 4,
            }.get(device.device_type, 5)
            risk_weight = 0 if device.risk_label == "trusted" else 1
            if not device.online:
                risk_weight = 3
            elif device.risk_label == "watch":
                risk_weight = 2
            return (risk_weight, type_weight, device.ip)

        return sorted(devices, key=weight)
