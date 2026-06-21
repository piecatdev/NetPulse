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
    parser.add_argument("cidr", help="Network to scan, e.g. 192.168.1.0/24")
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
        choices=["table", "map", "cards"],
        default="map",
        help="Initial dashboard view for --demo mode",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scan and print results without the live dashboard",
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
            with contextlib.suppress(asyncio.CancelledError):
                await stop_event.wait()
            await _cancel_dashboard_tasks(scan_task, input_task)
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
            with contextlib.suppress(asyncio.CancelledError):
                await stop_event.wait()
            await _cancel_dashboard_tasks(input_task)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]NetPulse demo closed[/]")


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
        if not engine.deep_scan:
            snapshot = await engine.arp_snapshot()
            if snapshot:
                state.apply_scan_results(snapshot)
                state.add_event(f"ARP snapshot: {len(snapshot)} visible hosts", "info")
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
    state.add_event("Input loop avviato", "info")
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
    try:
        asyncio.run(run(parser.parse_args()))
    except KeyboardInterrupt:
        print("\nNetPulse interrupted by user")


if __name__ == "__main__":
    main()
