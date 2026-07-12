from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .demo import demo_registry, demo_scan_results
from .input import KeyboardInput, LineKeyboardInput
from .memory import DeviceMemoryRecord
from .network import NetworkEngine
from .persistence import DeviceRegistry, RegistryError
from .state import NetworkState
from .storage import HistoryStore
from .ui import Dashboard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netpulse",
        description="Monitor device presence and latency on a local network.",
    )
    parser.add_argument("cidr", nargs="?", help="Network to scan, e.g. 192.168.1.0/24")
    parser.add_argument("--interval", type=_positive_float, default=5.0, help="Seconds between scans in --watch mode")
    parser.add_argument("--timeout", type=_positive_float, default=1.0, help="Ping timeout per host")
    parser.add_argument("--concurrency", type=_positive_int, default=64, help="Concurrent ping probes")
    parser.add_argument(
        "--deep-scan",
        action="store_true",
        help="Ping the whole subnet instead of using ARP-first discovery",
    )
    parser.add_argument(
        "--resolve-names",
        action="store_true",
        help="Try reverse-DNS hostname resolution (can be slow on Windows)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep scanning every --interval seconds; default mode refreshes manually with R",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Load a synthetic LAN snapshot for screenshots without scanning the real network",
    )
    parser.add_argument(
        "--demo-view",
        choices=["table", "map", "memory", "cards"],
        default="map",
        help="Initial dashboard view for --demo mode",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scan and print results without the live dashboard",
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="Show remembered devices and recent history without scanning",
    )
    parser.add_argument(
        "--timeline",
        metavar="DEVICE",
        help="Show recent events for a remembered device by MAC, IP, id, or name",
    )
    parser.add_argument(
        "--baseline",
        choices=["show", "save", "diff", "reset"],
        help="Manage the approved remembered network baseline",
    )
    parser.add_argument(
        "--history-limit",
        type=_positive_int,
        default=10,
        help="Rows to show for --memory and --timeline",
    )
    parser.add_argument(
        "--diag",
        action="store_true",
        help="Print discovery diagnostics and Python paths without the live dashboard",
    )
    parser.add_argument(
        "--arp-only",
        action="store_true",
        help="With --once, show only devices present in the ARP cache",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="With --once, print a plain list instead of a Rich table",
    )
    parser.add_argument(
        "--alt-screen",
        action="store_true",
        help="Use Rich's alternate full-screen buffer",
    )
    parser.add_argument(
        "--key-test",
        action="store_true",
        help="Test terminal key input for 15 seconds",
    )
    parser.add_argument(
        "--line-input",
        action="store_true",
        help="Use typed commands followed by Enter instead of direct key input",
    )
    parser.add_argument(
        "--input-log",
        type=Path,
        help="Write dashboard key commands to a log file",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("devices.json"),
        help="JSON file mapping MAC addresses to friendly names",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=Path("netpulse.db"),
        help="SQLite database for history, metrics, and timelines",
    )
    parser.add_argument(
        "--retention-days",
        type=_non_negative_int,
        default=0,
        help="Delete metrics/events older than this many days on startup; 0 disables pruning",
    )
    return parser


async def run(args: argparse.Namespace) -> None:
    console = Console()

    if _history_command_requested(args):
        run_history_command(console, args)
        return

    if args.demo:
        state = NetworkState(demo_registry(), gateway_ip="192.168.1.1")
        state.add_event("NetPulse started in demo mode", "info")
        await run_demo(
            console,
            state,
            alt_screen=args.alt_screen,
            line_input=args.line_input,
            plain=args.plain,
            initial_view=args.demo_view,
        )
        return

    registry = DeviceRegistry(args.registry)
    try:
        registry.load()
    except RegistryError as exc:
        console.print(f"[bold red]Registry error:[/] {exc}")
        raise SystemExit(2) from exc

    engine = NetworkEngine(
        cidr=args.cidr,
        interval=args.interval,
        concurrency=args.concurrency,
        timeout=args.timeout,
        deep_scan=args.deep_scan,
        resolve_names=args.resolve_names,
    )
    history = HistoryStore(args.history, retention_days=args.retention_days)
    history.connect()

    state = NetworkState(registry, history=history, gateway_ip=engine.gateway_ip)
    state.add_event("NetPulse started", "info")

    if args.key_test:
        await run_key_test(console)
        history.close()
        return

    if args.diag:
        await run_diagnostics(console, engine, state)
        history.close()
        return

    if args.once:
        await run_once(console, engine, state, arp_only=args.arp_only, plain=args.plain)
        history.close()
        return

    await run_initial_scan(engine, state)
    dashboard = Dashboard(state, alt_screen=args.alt_screen, line_input=args.line_input)
    stop_event = asyncio.Event()
    scan_now = asyncio.Event()

    try:
        scan_task: asyncio.Task | None = None
        input_task: asyncio.Task | None = None
        with dashboard.live() as live:
            scan_task = asyncio.create_task(
                _scan_loop(engine, state, stop_event, scan_now, watch=args.watch, live=live)
            )
            input_task = asyncio.create_task(
                _input_loop(
                    state,
                    stop_event,
                    scan_now,
                    live=live,
                    line_input=args.line_input,
                    input_log=args.input_log,
                )
            )
            await _run_dashboard_workers(stop_event, scan_task, input_task)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]NetPulse interrupted by user[/]")
    finally:
        history.close()


async def _cancel_dashboard_tasks(*tasks: asyncio.Task | None) -> None:
    active_tasks = [task for task in tasks if task is not None and not task.done()]
    for task in active_tasks:
        task.cancel()
    for task in active_tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _run_dashboard_workers(
    stop_event: asyncio.Event,
    *workers: asyncio.Task,
) -> None:
    """Run dashboard workers until shutdown or the first worker terminates."""
    stop_task = asyncio.create_task(stop_event.wait())
    try:
        done, _ = await asyncio.wait(
            (stop_task, *workers),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_event.is_set():
            return

        completed_workers = [task for task in done if task is not stop_task]
        for task in completed_workers:
            task.result()
        raise RuntimeError("A dashboard worker stopped before shutdown was requested")
    finally:
        stop_event.set()
        await _cancel_dashboard_tasks(stop_task, *workers)


async def run_initial_scan(engine: NetworkEngine, state: NetworkState) -> None:
    state.add_event("Initial manual scan requested", "info")
    await _run_scan(engine, state)


async def run_demo(
    console: Console,
    state: NetworkState,
    *,
    alt_screen: bool = False,
    line_input: bool = False,
    plain: bool = False,
    initial_view: str = "map",
) -> None:
    state.apply_scan_results(demo_scan_results())
    state.view_mode = initial_view
    state.add_event("Demo snapshot loaded: synthetic devices only", "info")
    state.last_action = "demo"

    if plain:
        _print_plain_devices(state)
        return

    dashboard = Dashboard(state, alt_screen=alt_screen, line_input=line_input)
    stop_event = asyncio.Event()
    scan_now = asyncio.Event()
    try:
        input_task: asyncio.Task | None = None
        with dashboard.live() as live:
            input_task = asyncio.create_task(
                _input_loop(
                    state,
                    stop_event,
                    scan_now,
                    live=live,
                    line_input=line_input,
                )
            )
            await _run_dashboard_workers(stop_event, input_task)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]NetPulse demo closed[/]")


def run_history_command(console: Console, args: argparse.Namespace) -> None:
    history = HistoryStore(args.history, retention_days=args.retention_days)
    history.connect()
    try:
        records = history.device_records()
        baseline_action = getattr(args, "baseline", None)
        if baseline_action:
            _run_baseline_command(console, history, records, baseline_action, args.history_limit)
            return
        if args.timeline:
            _print_device_timeline(console, history, records, args.timeline, args.history_limit)
            return
        _print_memory_report(console, history, records, args.history_limit)
    finally:
        history.close()


def _run_baseline_command(
    console: Console,
    history: HistoryStore,
    records: list[DeviceMemoryRecord],
    action: str,
    limit: int,
) -> None:
    if action == "save":
        saved = history.save_baseline(records)
        console.print(f"[bold green]Baseline saved[/] devices={saved}")
        if saved == 0:
            console.print("Run a scan first so NetPulse has devices to approve.")
        return
    if action == "reset":
        removed = history.clear_baseline()
        console.print(f"[bold yellow]Baseline reset[/] removed={removed}")
        return
    if action == "show":
        _print_baseline(console, history.baseline_records(), history.baseline_saved_at(), limit)
        return
    _print_baseline_diff(
        console,
        baseline=history.baseline_records(),
        current=records,
        saved_at=history.baseline_saved_at(),
        limit=limit,
    )


def _print_baseline(
    console: Console,
    baseline: list[DeviceMemoryRecord],
    saved_at: str | None,
    limit: int,
) -> None:
    console.print(
        f"[bold cyan]NetPulse baseline[/] devices={len(baseline)} "
        f"saved={_short_time(saved_at or '')}"
    )
    table = Table(title="Approved devices")
    table.add_column("Device", no_wrap=True, overflow="ellipsis")
    table.add_column("IP", no_wrap=True)
    table.add_column("Type", no_wrap=True)
    table.add_column("Risk", no_wrap=True)
    for record in baseline[:limit]:
        table.add_row(
            _clip_plain(record.name, 22),
            record.ip or "n/d",
            record.device_type,
            record.risk_label,
        )
    if not baseline:
        table.add_row("No approved baseline", "", "", "")
    console.print(table)


def _print_baseline_diff(
    console: Console,
    *,
    baseline: list[DeviceMemoryRecord],
    current: list[DeviceMemoryRecord],
    saved_at: str | None,
    limit: int,
) -> None:
    findings = _baseline_findings(baseline, current)
    status = "matches" if not findings and baseline else "needs review"
    console.print(
        f"[bold cyan]NetPulse baseline diff[/] status={status} "
        f"baseline={len(baseline)} current={len(current)} saved={_short_time(saved_at or '')}"
    )

    table = Table(title="Baseline changes")
    table.add_column("Change", no_wrap=True)
    table.add_column("Device", no_wrap=True, overflow="ellipsis")
    table.add_column("Detail", overflow="ellipsis")
    for change, device, detail in findings[:limit]:
        table.add_row(change, _clip_plain(device, 24), _clip_plain(detail, 76))
    if not baseline:
        table.add_row("setup", "No baseline", "Run netpulse --baseline save after reviewing --memory")
    elif not findings:
        table.add_row("ok", "Baseline", "Current memory matches approved devices")
    console.print(table)


def _baseline_findings(
    baseline: list[DeviceMemoryRecord],
    current: list[DeviceMemoryRecord],
) -> list[tuple[str, str, str]]:
    baseline_by_id = {record.device_id: record for record in baseline}
    current_by_id = {record.device_id: record for record in current}
    findings: list[tuple[str, str, str]] = []

    for record in current:
        approved = baseline_by_id.get(record.device_id)
        if approved is None:
            findings.append(("new", record.name, f"{record.ip} {record.device_type} {record.risk_label}"))
            continue
        if approved.ip != record.ip:
            findings.append(("ip", record.name, f"{approved.ip or 'n/d'} -> {record.ip or 'n/d'}"))
        if approved.device_type != record.device_type:
            findings.append(("type", record.name, f"{approved.device_type} -> {record.device_type}"))
        if approved.risk_label != record.risk_label:
            findings.append(("risk", record.name, f"{approved.risk_label} -> {record.risk_label}"))

    for record in baseline:
        if record.device_id not in current_by_id:
            findings.append(("missing", record.name, f"Last approved at {record.ip or 'n/d'}"))

    return findings


def _print_memory_report(
    console: Console,
    history: HistoryStore,
    records: list[DeviceMemoryRecord],
    limit: int,
) -> None:
    known = sum(1 for record in records if record.known)
    unknown = len(records) - known
    latency_rows = history.latency_summary(limit=max(limit, 10))
    baseline = history.baseline_records()
    baseline_findings = _baseline_findings(baseline, records) if baseline else []
    console.print(
        f"[bold cyan]NetPulse memory[/] devices={len(records)} "
        f"known={known} unknown={unknown}"
    )
    console.print(_memory_status_line(records, unknown, latency_rows, baseline, baseline_findings))

    devices = Table(title="Remembered devices")
    devices.add_column("Device", no_wrap=True, overflow="ellipsis")
    devices.add_column("IP", no_wrap=True)
    devices.add_column("Type", no_wrap=True)
    devices.add_column("Risk", no_wrap=True)
    devices.add_column("Last seen", no_wrap=True)

    for record in records[:limit]:
        devices.add_row(
            _clip_plain(record.name, 22),
            record.ip or "n/d",
            record.device_type,
            record.risk_label,
            _short_time(record.last_seen),
        )
    if not records:
        devices.add_row("No remembered devices", "", "", "", "")
    console.print(devices)

    if latency_rows:
        names_by_id = {record.device_id: record.name for record in records}
        latency = Table(title="Latency signals")
        latency.add_column("Device", no_wrap=True, overflow="ellipsis")
        latency.add_column("Samples", justify="right")
        latency.add_column("Average", justify="right")
        latency.add_column("Peak", justify="right")
        for device_id, samples, average, peak in latency_rows[:limit]:
            latency.add_row(
                _clip_plain(names_by_id.get(device_id, device_id), 28),
                str(samples),
                _latency_value(average),
                _latency_value(peak),
            )
        console.print(latency)

    events = history.recent_events(limit=limit)
    event_table = Table(title="Recent events")
    event_table.add_column("Time", no_wrap=True)
    event_table.add_column("Level", no_wrap=True)
    event_table.add_column("Event", overflow="ellipsis")
    for captured_at, _device_id, level, message in events:
        event_table.add_row(_short_time(captured_at), level, _clip_plain(message, 72))
    if not events:
        event_table.add_row("n/d", "info", "No events recorded yet")
    console.print(event_table)


def _memory_status_line(
    records: list[DeviceMemoryRecord],
    unknown_count: int,
    latency_rows: list[tuple[str, int, float | None, float | None]],
    baseline: list[DeviceMemoryRecord],
    baseline_findings: list[tuple[str, str, str]],
) -> str:
    high_latency_count = sum(1 for _device_id, _samples, average, peak in latency_rows if (peak or average or 0) > 350)
    if not records:
        status = "no history"
        detail = "run a scan to create local memory"
    elif not baseline:
        status = "learning"
        detail = "baseline not saved"
    elif baseline_findings:
        status = "needs review"
        detail = f"{len(baseline_findings)} baseline change(s)"
    else:
        status = "approved"
        detail = "current memory matches the approved baseline"

    signals = [detail]
    if unknown_count:
        signals.append(f"{unknown_count} unknown")
    if high_latency_count:
        signals.append(f"{high_latency_count} high-latency")
    return f"Network status: {status} ({'; '.join(signals)})"


def _print_device_timeline(
    console: Console,
    history: HistoryStore,
    records: list[DeviceMemoryRecord],
    query: str,
    limit: int,
) -> None:
    record = _find_memory_record(records, query)
    if record is None:
        console.print(f"[bold red]No remembered device matches:[/] {query}")
        console.print("Use [bold]netpulse --memory[/] to see remembered devices.")
        return

    console.print(
        f"[bold cyan]NetPulse timeline[/] {record.name} "
        f"[dim]{record.ip} {record.mac or 'unknown'}[/]"
    )
    table = Table(title="Recent device events")
    table.add_column("Time", no_wrap=True)
    table.add_column("Level", no_wrap=True)
    table.add_column("Event", overflow="ellipsis")
    rows = history.timeline(record.device_id, limit=limit)
    for captured_at, level, message in rows:
        table.add_row(_short_time(captured_at), level, _clip_plain(message, 72))
    if not rows:
        table.add_row("n/d", "info", "No events recorded for this device")
    console.print(table)


def _find_memory_record(records: list[DeviceMemoryRecord], query: str) -> DeviceMemoryRecord | None:
    needle = query.strip().lower().replace("-", ":")
    for record in records:
        candidates = {
            record.device_id.lower(),
            record.mac.lower(),
            record.ip.lower(),
            record.name.lower(),
        }
        if needle in candidates:
            return record
    for record in records:
        if needle and needle in record.name.lower():
            return record
    return None


def _short_time(value: str) -> str:
    if not value:
        return "n/d"
    if "T" in value:
        value = value.replace("T", " ")
    return value[:16]


def _latency_value(value: float | None) -> str:
    if value is None:
        return "n/d"
    return f"{value:.0f} ms"


def _clip_plain(value: str, width: int) -> str:
    single_line = value.replace("\n", " ")
    if len(single_line) <= width:
        return single_line
    return single_line[: max(0, width - 1)] + "~"


def _history_command_requested(args: argparse.Namespace) -> bool:
    return bool(args.memory or args.timeline or getattr(args, "baseline", None))


def _cidr_not_required(args: argparse.Namespace) -> bool:
    return bool(args.demo or _history_command_requested(args))


async def run_once(
    console: Console,
    engine: NetworkEngine,
    state: NetworkState,
    *,
    arp_only: bool = False,
    plain: bool = False,
) -> None:
    console.print(
        f"[bold cyan]NetPulse scan[/] gateway={engine.gateway_ip or 'n/d'} "
        f"mode={'deep' if engine.deep_scan else 'arp-first'} hosts={engine.host_count}"
    )
    results = await engine.arp_snapshot() if arp_only else await engine.scan_once()
    state.apply_scan_results(results)

    if plain:
        _print_plain_devices(state)
        return

    table = Table(title=f"Detected devices: {len(state.devices)}")
    table.add_column("IP")
    table.add_column("MAC")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Risk")
    table.add_column("Latency", justify="right")

    for device in state.sorted_devices():
        latency = "n/d" if device.latency_ms is None else f"{device.latency_ms:.0f} ms"
        table.add_row(
            device.ip,
            device.mac or "unknown",
            device.name,
            device.device_type,
            device.risk_label,
            latency,
        )

    console.print(table)


def _print_plain_devices(state: NetworkState) -> None:
    print(f"devices={len(state.devices)}")
    for device in state.sorted_devices():
        latency = "n/d" if device.latency_ms is None else f"{device.latency_ms:.0f}ms"
        print(
            f"{device.ip:<15} {device.mac or 'unknown':<17} "
            f"{device.device_type:<8} {device.risk_label:<8} {latency:<8} {device.name}"
        )


async def run_diagnostics(console: Console, engine: NetworkEngine, state: NetworkState) -> None:
    import netpulse
    import netpulse.cli
    import netpulse.network

    console.print("[bold cyan]NetPulse diagnostics[/]")
    console.print(f"python: {sys.executable}")
    console.print(f"cwd: {Path.cwd()}")
    console.print(f"netpulse: {netpulse.__file__}")
    console.print(f"cli: {netpulse.cli.__file__}")
    console.print(f"network: {netpulse.network.__file__}")
    console.print(f"cidr: {engine.network}")
    console.print(f"gateway: {engine.gateway_ip or 'n/d'}")
    console.print(f"mode: {'deep' if engine.deep_scan else 'arp-first'}")

    snapshot = await engine.arp_snapshot()
    console.print(f"arp snapshot in subnet: {len(snapshot)}")
    for item in snapshot[:10]:
        console.print(f"  arp {item.ip} {item.mac}")

    results = await engine.scan_once()
    state.apply_scan_results(results)
    console.print(f"scan results: {len(results)}")
    console.print(f"state devices: {len(state.devices)}")
    for device in state.sorted_devices()[:10]:
        latency = "n/d" if device.latency_ms is None else f"{device.latency_ms:.0f} ms"
        console.print(f"  device {device.ip} {device.mac or 'no-mac'} {latency}")


async def run_key_test(console: Console) -> None:
    keyboard = KeyboardInput()
    console.print("[bold cyan]NetPulse key test[/]")
    console.print("Press arrows, H/J/K/L, V, R, Q. The test ends automatically after 15 seconds.")
    deadline = asyncio.get_running_loop().time() + 15
    while asyncio.get_running_loop().time() < deadline:
        try:
            action = await asyncio.wait_for(keyboard.read_action(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        console.print(f"action={action.name}")
        if action.name == "quit":
            break


async def _scan_loop(
    engine: NetworkEngine,
    state: NetworkState,
    stop_event: asyncio.Event,
    scan_now: asyncio.Event,
    *,
    watch: bool = False,
    live=None,
) -> None:
    while not stop_event.is_set():
        scan_now.clear()
        try:
            if watch:
                await asyncio.wait_for(scan_now.wait(), timeout=engine.interval)
            else:
                await scan_now.wait()
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            break
        await _run_scan(engine, state, live=live)


async def _run_scan(engine: NetworkEngine, state: NetworkState, *, live=None) -> None:
    state.scanning = True
    if live is not None:
        live.refresh()
    try:
        state.add_event(
            f"Scan started ({'deep' if engine.deep_scan else 'arp-first'}, up to {engine.host_count} hosts)",
            "info",
        )
        results = await engine.scan_once()
        state.apply_scan_results(results)
        state.add_event(f"Scan complete: {len(results)} active hosts", "info")
    except Exception as exc:
        state.add_event(f"Scan error: {exc}", "error")
    finally:
        state.scanning = False
        if live is not None:
            live.refresh()


async def _input_loop(
    state: NetworkState,
    stop_event: asyncio.Event,
    scan_now: asyncio.Event,
    *,
    live=None,
    line_input: bool = False,
    input_log: Path | None = None,
) -> None:
    keyboard = LineKeyboardInput() if line_input else KeyboardInput()
    state.add_event("Input loop started", "info")
    _write_input_log(input_log, "input-loop-started")
    if live is not None:
        live.refresh()

    while not stop_event.is_set():
        action = await keyboard.read_action()
        if action.name == "noop":
            continue
        _write_input_log(input_log, f"action={action.name}")
        if action.name == "quit":
            state.last_action = "quit"
            state.add_event("Shutdown requested", "info")
            stop_event.set()
        elif action.name == "refresh":
            state.last_action = "refresh"
            state.add_event("Manual scan requested", "info")
            scan_now.set()
        elif action.name == "view":
            state.cycle_view()
        elif action.name in {"left", "right", "up", "down"}:
            if state.view_mode == "memory":
                state.scroll_memory(_memory_scroll_offset(action.name))
            elif state.view_mode == "map":
                state.move_attention_selection(_selection_offset(state.view_mode, action.name))
            else:
                state.move_selection(_selection_offset(state.view_mode, action.name))
        if live is not None:
            live.refresh()


def _selection_offset(view_mode: str, action_name: str) -> int:
    if view_mode == "table":
        return {
            "up": -1,
            "down": 1,
            "left": -14,
            "right": 14,
        }[action_name]
    if view_mode == "cards":
        return {
            "up": -3,
            "down": 3,
            "left": -1,
            "right": 1,
        }[action_name]
    return {
        "up": -1,
        "down": 1,
        "left": -6,
        "right": 6,
    }[action_name]


def _memory_scroll_offset(action_name: str) -> int:
    return {
        "up": -1,
        "down": 1,
        "left": -7,
        "right": 7,
    }[action_name]


def _write_input_log(path: Path | None, line: str) -> None:
    if path is None:
        return
    try:
        with path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
    except OSError:
        return


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return parsed


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.cidr is None and not _cidr_not_required(args):
        parser.error("cidr is required unless --demo, --memory, or --timeline is used")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nNetPulse interrupted by user")


if __name__ == "__main__":
    main()
