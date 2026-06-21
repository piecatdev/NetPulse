from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console

from .persistence import DeviceRegistry, RegistryError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netpulse-rename",
        description="Assign a friendly name to a MAC address in the JSON registry.",
    )
    parser.add_argument("mac", help="MAC address, e.g. aa:bb:cc:dd:ee:ff")
    parser.add_argument("name", nargs="+", help="Friendly device name")
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("devices.json"),
        help="JSON registry used by NetPulse",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    console = Console()
    registry = DeviceRegistry(args.registry)
    try:
        registry.load()
    except RegistryError as exc:
        console.print(f"[bold red]Registry error:[/] {exc}")
        raise SystemExit(2) from exc
    name = " ".join(args.name)
    try:
        registry.set_name(args.mac, name)
    except RegistryError as exc:
        console.print(f"[bold red]Registry error:[/] {exc}")
        raise SystemExit(2) from exc
    console.print(f"[green]OK[/] {args.mac} -> [bold]{name}[/]")


if __name__ == "__main__":
    main()
