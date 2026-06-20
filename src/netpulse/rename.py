from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console

from .persistence import DeviceRegistry


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
    registry = DeviceRegistry(args.registry)
    registry.load()
    name = " ".join(args.name)
    registry.set_name(args.mac, name)
    Console().print(f"[green]OK[/] {args.mac} -> [bold]{name}[/]")


if __name__ == "__main__":
    main()
