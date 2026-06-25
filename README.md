<div align="center">
  <img src="assets/logo.png" width="420" alt="NetPulse">
  <p><strong>Local network discovery, presence monitoring, and signal mapping in your terminal.</strong></p>
</div>

# NetPulse

NetPulse is a Python CLI/TUI for discovering, inspecting, and visualizing devices on a local network. It uses `asyncio` for non-blocking scans and `Rich` for a terminal dashboard with a strong visual identity.

![NetPulse dashboard demo](assets/demo-dashboard.png)

## Highlights

- ARP-first discovery with optional deep subnet scans.
- Interactive Rich dashboard with table, card, and signal-map views.
- Local-only device intelligence for vendor, type, risk, and known-device status.
- Network Memory compares each scan against remembered devices and surfaces drift.
- SQLite history for snapshots, latency metrics, events, alerts, and timelines.
- Screenshot-safe demo mode with synthetic devices and no real network scan.

## Quick Start

Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
netpulse 192.168.1.0/24
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
netpulse 192.168.1.0/24
```

Preview the dashboard with synthetic data:

```bash
netpulse 192.168.1.0/24 --demo
```

## Project Structure

```text
NetPulse/
  pyproject.toml
  README.md
  src/netpulse/
    cli.py          # CLI entrypoint and runtime wiring
    models.py       # shared dataclasses
    network.py      # Network Engine: async ping + ARP table discovery
    persistence.py  # JSON registry for MAC -> friendly name
    state.py        # runtime state, selection, events, timelines
    intelligence.py # local vendor/type/risk classification
    storage.py      # SQLite history, metrics, and event storage
    input.py        # interactive keyboard handling
    rename.py       # helper command for friendly device names
    ui.py           # Rich dashboard and visual rendering
```

## Installation

Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Usage

```bash
netpulse 192.168.1.0/24 --timeout 1
```

By default, NetPulse uses **manual dashboard mode**:

- it loads an initial ARP snapshot;
- it stays stable and navigable;
- it refreshes only when you press `R`.

This keeps the ASCII map readable and avoids constant layout movement.

For continuous monitoring:

```bash
netpulse 192.168.1.0/24 --watch --interval 5
```

For screenshots or demos without scanning your real network:

```bash
netpulse 192.168.1.0/24 --demo
```

For a deeper subnet scan:

```bash
netpulse 192.168.1.0/24 --deep-scan
```

For reverse-DNS hostname resolution:

```bash
netpulse 192.168.1.0/24 --resolve-names
```

Note: `--resolve-names` can be slow on Windows if the network does not answer reverse DNS queries quickly.

## Cross-Platform Notes

NetPulse is intended to run on Windows, macOS, and Linux. Discovery is local-only
and depends on operating-system networking tools:

- `ping` is used for active probes, with OS-specific timeout flags.
- `arp -a` is used for the ARP-cache snapshot.
- Windows uses `route print` to detect the default gateway when possible.
- macOS uses `route -n get default` to detect the default gateway when possible.
- Linux uses `ip route show default` to detect the default gateway when possible.
- If gateway detection fails, NetPulse estimates the gateway from the scanned
  subnet.
- Direct dashboard key input uses Windows console events on Windows and POSIX
  terminal input on macOS/Linux.

If direct key input is unreliable in a terminal, use `--line-input` and type
commands followed by Enter.

The automated test suite runs on Windows, macOS, and Linux in GitHub Actions.
For local troubleshooting, start with `--demo`, then `--diag`, then
`--once --plain` against your real subnet.

## Dashboard

The dashboard includes:

- a status header with time, view, scan state, and online counts;
- a compact device table;
- device cards;
- an estimated ASCII-art network map;
- a Network Memory view for baseline drift and health/trust scoring;
- a selected-node detail panel;
- a fixed-height signal log.

Interactive controls:

- `Arrows` or `H/J/K/L`: move the selected device;
- `V`: switch between table, map, Network Memory, and cards;
- `R`: run a manual refresh;
- `Q`: quit.

In table view, up/down moves one device at a time. In card view, up/down follows the grid.

If direct key input is unreliable in your terminal, use:

```bash
netpulse 192.168.1.0/24 --line-input
```

Then type commands followed by Enter: `j`, `k`, `v`, `r`, `q`.

## Device Intelligence

NetPulse enriches each device with local-only intelligence:

- vendor estimate from MAC/OUI prefixes;
- estimated type: `gateway`, `host`, `mobile`, `storage`, `iot`;
- identity confidence: `high`, `medium`, or `low`;
- identity signals such as saved name, hostname, MAC vendor, gateway IP, and
  type hint;
- risk label: `trusted`, `unknown`, `watch`;
- numeric risk score.

The classification is conservative and local. It uses hostname hints, known OUI
prefixes, MAC presence, saved names, and gateway detection. The detail panel
shows why NetPulse believes an identity is more or less reliable.

## Network Overview

The map view is a clean operational overview rather than a physical topology. It shows:

- the NetPulse ASCII header;
- detected or estimated gateway;
- online, attention, offline, and trusted counts;
- devices ordered by what needs attention first;
- selected-node focus.

This view is designed for quick interpretation: use it to spot unknown/watch devices, high-level network state, and the currently focused node without reading the full device table.

## Network Memory

NetPulse remembers devices through its local SQLite history and compares each new scan against that memory. The `memory` dashboard view summarizes:

- network health score;
- trust score;
- drift level: `stable`, `low`, `medium`, or `high`;
- new devices;
- missing remembered devices;
- IP changes;
- known-profile or type drift.

This turns NetPulse from a point-in-time scanner into a local-first network memory tool. The comparison is fully local and uses only the stored history database.

## Visual Identity

NetPulse uses a focused terminal palette:

- electric cyan for structure, links, and primary surfaces;
- pulse green for online/trusted state;
- amber for selection, unknown, and watch states;
- hot red for offline or error states.

The goal is to make the tool feel like a local network command center rather than a plain scanner.

## History And Timeline

NetPulse stores runtime history in `netpulse.db`:

- device snapshots;
- latency metrics;
- connection/disconnection events;
- alerts;
- per-device timeline events.

You can choose a different history database:

```bash
netpulse 192.168.1.0/24 --history lan-history.db
```

By default, NetPulse keeps all stored metrics and events. To prune old runtime
history on startup, set a retention window:

```bash
netpulse 192.168.1.0/24 --watch --retention-days 30
```

You can inspect remembered history without starting a scan:

```bash
netpulse --memory
```

Show a device timeline by MAC, IP, remembered id, or name:

```bash
netpulse --timeline 192.168.1.24
netpulse --timeline "NAS Vault"
```

Limit report rows when you want a shorter view:

```bash
netpulse --memory --history-limit 5
```

After reviewing remembered devices, save an approved baseline:

```bash
netpulse --baseline save
```

Compare current memory against that approved baseline:

```bash
netpulse --baseline diff
```

You can also inspect or clear the approved baseline:

```bash
netpulse --baseline show
netpulse --baseline reset
```

## Friendly Names

NetPulse uses `devices.json` to associate friendly names with MAC addresses:

```json
{
  "devices": {
    "aa:bb:cc:dd:ee:ff": {
      "name": "Studio Laptop"
    },
    "11:22:33:44:55:66": {
      "name": "NAS"
    }
  }
}
```

You can rename a device from the CLI:

```bash
netpulse-rename aa:bb:cc:dd:ee:ff "Studio Laptop"
```

On the next scan, the device will use the friendly name instead of the fallback `Host <ip>`.

## Diagnostics

Run one scan without the live dashboard:

```bash
netpulse 192.168.1.0/24 --once
```

Show only ARP-cache devices:

```bash
netpulse 192.168.1.0/24 --once --arp-only
```

Use plain text output:

```bash
netpulse 192.168.1.0/24 --once --plain
```

Print discovery diagnostics:

```bash
netpulse 192.168.1.0/24 --diag
```

Test keyboard input:

```bash
netpulse 192.168.1.0/24 --key-test
```

If the dashboard does not react to keys in a specific terminal, rerun with
`--line-input`. The scan behavior is the same; only command entry changes.

## Development

Run the unit tests with the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -v
```

On macOS/Linux:

```bash
.venv/bin/python -B -m unittest discover -v
```

The GitHub Actions test workflow runs this suite on Windows, macOS, and Linux
for Python 3.10, 3.11, and 3.12.

If you want to run a full bytecode compilation check on Windows/OneDrive,
write Python's cache outside the project directory:

```powershell
$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'netpulse-pycache'
.\.venv\Scripts\python.exe -m compileall src tests
```
