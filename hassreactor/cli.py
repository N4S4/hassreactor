"""
CLI for hassreactor — scaffolding, wizard, discovery, templates.

Usage:
    hassreactor init               Create automations.py
    hassreactor wizard             Interactive automation builder
    hassreactor discover           Show entities with suggestions
    hassreactor init --template X  Generate from a template
"""
from __future__ import annotations

import os
import sys
from argparse import ArgumentParser

# ── Templates ───────────────────────────────────────────────────────────────

_TEMPLATES = {
    "motion": '''"""
Motion sensor → light automation.
When motion is detected, turn on light. Turn off after 5 min of no motion.
"""
from hassreactor import Reactor

HA_URL = "http://homeassistant:8123"
HA_TOKEN = "your-long-lived-token-here"

app = Reactor(HA_URL, HA_TOKEN)


@app.when("binary_sensor.motion_sensor", to="on")
async def motion_detected(event):
    """Motion detected — turn on light."""
    app.log.info("Motion detected!")
    await app.light.turn_on(entity_id="light.motion_light")
    app.store["last_motion"] = True


@app.when("binary_sensor.motion_sensor", to="off", for_="5m")
async def no_motion(event):
    """No motion for 5 minutes — turn off light."""
    app.log.info("No motion for 5 min")
    await app.light.turn_off(entity_id="light.motion_light")


if __name__ == "__main__":
    app.run()
''',

    "climate": '''"""
Temperature-based climate control.
Turn on fan above threshold, turn off below threshold.
"""
from hassreactor import Reactor

HA_URL = "http://homeassistant:8123"
HA_TOKEN = "your-long-lived-token-here"

app = Reactor(HA_URL, HA_TOKEN)


@app.when("sensor.temperature_sensor", above=28)
async def too_hot(event):
    """Temperature crossed above 28°C — turn on fan/AC."""
    app.log.info("Too hot! %.1f°C", float(event.state))
    await app.fan.turn_on(entity_id="fan.cooling_fan")
    await app.climate.set_temperature(
        entity_id="climate.thermostat", temperature=24
    )


@app.when("sensor.temperature_sensor", below=25)
async def cooled_down(event):
    """Temperature back to normal."""
    app.log.info("Cooled down to %.1f°C", float(event.state))
    await app.fan.turn_off(entity_id="fan.cooling_fan")


@app.schedule("every 1h")
async def report():
    """Hourly temperature log."""
    temp = await app.get_state("sensor.temperature_sensor")
    app.log.info("Temperature: %s°C", temp)


if __name__ == "__main__":
    app.run()
''',

    "alarm": '''"""
Door/window open → notification alarm.
Notify when any monitored door or window opens.
"""
from hassreactor import Reactor

HA_URL = "http://homeassistant:8123"
HA_TOKEN = "your-long-lived-token-here"

app = Reactor(HA_URL, HA_TOKEN)

DOORS = [
    "binary_sensor.front_door",
    "binary_sensor.back_door",
    "binary_sensor.window_kitchen",
]


for door in DOORS:
    @app.when(door, to="on")
    async def door_opened(event):
        """A door/window opened — send notification."""
        app.log.info("Opened: %s", event.entity_id)
        await app.notify.telegram(message=f"🔔 {event.entity_id} opened!")


if __name__ == "__main__":
    app.run()
''',

    "leak": '''"""
Leak sensor → valve close + notification.
When water is detected, close the valve and alert.
"""
from hassreactor import Reactor

HA_URL = "http://homeassistant:8123"
HA_TOKEN = "your-long-lived-token-here"

app = Reactor(HA_URL, HA_TOKEN)


@app.when("binary_sensor.leak_sensor", to="on")
async def leak_detected(event):
    """Water leak! Close valve and alert."""
    app.log.critical("WATER LEAK DETECTED!")
    await app.valve.close(entity_id="valve.main_water")
    await app.notify.telegram(
        message="🚨 WATER LEAK! Main valve closed."
    )


@app.when("binary_sensor.leak_sensor", to="off", for_="1m")
async def leak_cleared(event):
    """Leak cleared — notify that it's safe."""
    app.log.info("Leak cleared")
    await app.notify.telegram(message="✅ Leak cleared. You can reopen the valve.")


if __name__ == "__main__":
    app.run()
''',
}


# ── Commands ────────────────────────────────────────────────────────────────


def cmd_init(path: str, force: bool, template: str = "") -> int:
    """Create automations.py from template."""
    if not path.endswith(".py"):
        path = os.path.join(path, "automations.py")

    if os.path.exists(path) and not force:
        print(f"File already exists: {path}")
        print("Use --force to overwrite.")
        return 1

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    if template and template in _TEMPLATES:
        content = _TEMPLATES[template]
        print(f"Using template: {template}")
    elif template:
        print(f"Unknown template: {template}")
        print(f"Available: {', '.join(sorted(_TEMPLATES))}")
        return 1
    else:
        content = _TEMPLATES["motion"]  # default

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Created: {path}")
    print(f"Run: python {path}")
    return 0


def cmd_wizard(ha_url: str, ha_token: str) -> int:
    """Interactive automation builder."""
    import asyncio

    print("\n🔮 hassreactor Wizard\n")
    print("Let's build your automation step by step.\n")

    # Categories
    print("What do you want to automate?")
    print("  [1] Motion sensor → light")
    print("  [2] Temperature → fan/climate")
    print("  [3] Door/window open → notification")
    print("  [4] Water leak → valve + alert")
    print("  [5] Schedule → hourly report")
    print("  [6] Custom (I know what I want)")

    choice = input("> ").strip()
    template_map = {
        "1": "motion", "2": "climate", "3": "alarm",
        "4": "leak", "5": "report",
    }
    if choice in template_map:
        tmpl = template_map[choice]
        if tmpl in _TEMPLATES:
            path = "automations.py"
            os.makedirs(".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(_TEMPLATES[tmpl])
            print(f"\n✅ Created {path}")
            print(f"   Edit the entity IDs, then run: python {path}")
            return 0

    if choice == "6":
        print("\nCustom mode not yet implemented.")
        print("Try: hassreactor init --template <name>")
        return 1

    print("\nInvalid choice.")
    return 1


def cmd_discover() -> int:
    """Discover entities and suggest automations."""
    import asyncio

    token = os.getenv("HA_TOKEN", "")
    url = os.getenv("HA_URL", "http://homeassistant:8123")
    if not token:
        # Try reading from .env
        env_paths = [".env", os.path.expanduser("~/.hermes/.env")]
        for ep in env_paths:
            if os.path.exists(ep):
                with open(ep) as f:
                    for line in f:
                        if line.startswith("HASS_TOKEN="):
                            token = line.strip().split("=", 1)[1]
                            break
                if token:
                    break
    if not token:
        print("Set HA_URL and HA_TOKEN env vars first.")
        return 1

    async def _discover():
        from hassreactor.engine import EventEngine
        engine = EventEngine(url, token, verify_ssl=False)

        try:
            await engine.connect()
            states = await engine.get_states()
        finally:
            await engine.disconnect()

        # Group by domain with suggestions
        groups: dict[str, list] = {}
        for s in states:
            eid = s.get("entity_id", "")
            domain = eid.split(".")[0] if "." in eid else "other"
            state = s.get("state", "?")
            name = s.get("attributes", {}).get("friendly_name", eid)
            groups.setdefault(domain, []).append((eid, state, name))

        # Priority domains for automation hints
        priority = [
            ("binary_sensor", "🚪", "→ @app.when(entity, to='on'): notify"),
            ("sensor", "📊", "→ @app.when(entity, above=X): trigger"),
            ("light", "💡", "→ @app.when(entity, to='on'): react"),
            ("switch", "🔌", "→ @app.when(entity, to='on'): react"),
            ("climate", "🌡️", "→ @app.schedule: report temp"),
            ("cover", "🪟", "→ @app.sun(after='sunset'): close"),
        ]

        print(f"\n🔍 Discovered {len(states)} entities\n")
        for domain, icon, hint in priority:
            items = groups.pop(domain, [])
            if not items:
                continue
            print(f"{icon} {domain} ({len(items)}) {hint}")
            for eid, state, name in items[:5]:
                print(f"   {eid}: {state} ({name})")
            if len(items) > 5:
                print(f"   ... and {len(items) - 5} more")
            print()

        # Remaining domains (no hints)
        for domain, items in sorted(groups.items()):
            print(f"📦 {domain} ({len(items)})")
            for eid, state, name in items[:3]:
                print(f"   {eid}: {state} ({name})")
            if len(items) > 3:
                print(f"   ... and {len(items) - 3} more")
            print()

        print("Run 'hassreactor wizard' to build automations interactively.")

    asyncio.run(_discover())
    return 0


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = ArgumentParser(
        prog="hassreactor",
        description="hassreactor — event-driven Home Assistant automations",
    )
    parser.add_argument("--version", action="store_true", help="Show version")

    sub = parser.add_subparsers(dest="command", help="Commands")

    # init
    init_p = sub.add_parser("init", help="Create automations.py")
    init_p.add_argument("--path", default=".", help="Output path")
    init_p.add_argument("--force", action="store_true", help="Overwrite")
    init_p.add_argument(
        "--template", default="",
        help=f"Template: {', '.join(sorted(_TEMPLATES))}"
    )

    # wizard
    wiz_p = sub.add_parser("wizard", help="Interactive builder")
    wiz_p.add_argument("--url", default="", help="HA URL")
    wiz_p.add_argument("--token", default="", help="HA token")

    # discover
    sub.add_parser("discover", help="Discover entities")

    args = parser.parse_args()

    if args.version:
        from hassreactor import __version__
        print(f"hassreactor {__version__}")
        return

    if args.command == "init":
        sys.exit(cmd_init(args.path, args.force, args.template))
    elif args.command == "wizard":
        sys.exit(cmd_wizard(args.url, args.token))
    elif args.command == "discover":
        sys.exit(cmd_discover())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
