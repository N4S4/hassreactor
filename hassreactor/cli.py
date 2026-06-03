"""
CLI for hassreactor — scaffolding and utilities.

Usage:
    hassreactor init          Create automations.py in current directory
    hassreactor init --force  Overwrite existing automations.py
    hassreactor init --path /path/to/dir   Create in specific directory
    hassreactor --version     Show version
"""
from __future__ import annotations

import sys
import os
from argparse import ArgumentParser

TEMPLATE = '''"""
Home Assistant automations powered by hassreactor.

Edit this file and run:
    python automations.py
"""
from hassreactor import Reactor

# Configuration — set these or use HA_URL / HA_TOKEN env vars
HA_URL = "http://homeassistant:8123"
HA_TOKEN = "your-long-lived-token-here"

app = Reactor(HA_URL, HA_TOKEN)


# ── Automations ──


@app.when("sensor.example_temperature", above=28)
async def too_hot(event):
    """When temperature goes above 28°C."""
    app.log.info("It's getting hot: %s°C", event.state)
    # await app.fan.turn_on(entity_id="fan.my_fan")


@app.when("binary_sensor.example_door", to="on")
async def door_opened(event):
    """When a door opens."""
    app.log.info("Door opened!")
    # await app.notify.telegram(message="Door opened!")


@app.schedule("every 1h")
async def hourly_report():
    """Log temperatures every hour."""
    temp = await app.get_state("sensor.example_temperature")
    app.log.info("Hourly report — temperature: %s°C", temp)


# ── Run ──

if __name__ == "__main__":
    app.run()
'''


def cmd_init(path: str, force: bool) -> int:
    """Create automations.py from template."""
    if not path.endswith(".py"):
        path = os.path.join(path, "automations.py")

    if os.path.exists(path) and not force:
        print(f"File already exists: {path}")
        print("Use --force to overwrite.")
        return 1

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(TEMPLATE)

    print(f"Created: {path}")
    print("Edit HA_URL, HA_TOKEN, then run:")
    print(f"  python {path}")
    return 0


def main() -> None:
    parser = ArgumentParser(
        prog="hassreactor",
        description="hassreactor — event-driven Home Assistant automations",
    )
    parser.add_argument(
        "--version", action="store_true",
        help="Show version and exit",
    )

    sub = parser.add_subparsers(dest="command", help="Commands")

    init_p = sub.add_parser("init", help="Create automations.py")
    init_p.add_argument(
        "--path", default=".",
        help="Output path or directory (default: ./automations.py)",
    )
    init_p.add_argument(
        "--force", action="store_true",
        help="Overwrite existing file",
    )

    args = parser.parse_args()

    if args.version:
        from hassreactor import __version__
        print(f"hassreactor {__version__}")
        return

    if args.command == "init":
        sys.exit(cmd_init(args.path, args.force))

    parser.print_help()


if __name__ == "__main__":
    main()
