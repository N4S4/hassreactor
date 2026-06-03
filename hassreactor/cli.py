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

    "report": '''"""
Hourly report — log sensor data and send summary.
Reads temperature and humidity every hour.
"""
from hassreactor import Reactor

HA_URL = "http://homeassistant:8123"
HA_TOKEN = "your-long-lived-token-here"

app = Reactor(HA_URL, HA_TOKEN)


@app.schedule("every 1h")
async def hourly_report():
    """Log temperature and humidity every hour."""
    temp = await app.get_state("sensor.temperature_sensor")
    humidity = await app.get_state("sensor.humidity_sensor")
    app.log.info("Report: %s°C, %s%% humidity", temp, humidity)


@app.schedule("0 9 * * *")
async def morning_summary():
    """Send a daily summary at 9am."""
    app.log.info("Good morning! Daily report ready.")


if __name__ == "__main__":
    app.run()
''',

    "custom": '''"""
Custom automation — fill in your own triggers and actions.
All trigger types are shown as comments. Uncomment what you need.
"""
from hassreactor import Reactor

HA_URL = "http://homeassistant:8123"
HA_TOKEN = "your-long-lived-token-here"

app = Reactor(HA_URL, HA_TOKEN)

# ── State triggers ──────────────────────────────────────────────────────
# @app.when("sensor.temperature", above=30)
# async def too_hot(event):
#     app.log.info("Too hot! %.1f°C", float(event.state))
#     await app.fan.turn_on(entity_id="fan.living_room")

# @app.when("sensor.temperature", below=20)
# async def too_cold(event):
#     await app.climate.set_temperature(entity_id="climate.home", temperature=22)

# @app.when("binary_sensor.door", to="on")
# async def door_opened(event):
#     await app.notify.telegram(message="Door opened!")

# @app.when("binary_sensor.door", to="on", for_="5m")
# async def door_open_too_long(event):
#     """State must persist for 5 minutes before firing."""
#     await app.notify.telegram(message="Door open for 5 minutes!")

# @app.when("sensor.humidity", changes=True, throttle="30s")
# async def humidity_changed(event):
#     """Fire at most once per 30 seconds."""
#     app.log.info("Humidity: %s%%", event.state)

# ── Sun triggers ────────────────────────────────────────────────────────
# @app.sun(after="sunset")
# async def lights_on():
#     await app.light.turn_on(entity_id="light.garden")

# @app.sun(before="sunrise", offset="30m")
# async def lights_off():
#     await app.light.turn_off(entity_id="light.garden")

# ── Event triggers ──────────────────────────────────────────────────────
# @app.on("call_service")
# async def on_service(event):
#     app.log.info("Service: %s", event.event_type)

# ── Schedule triggers ───────────────────────────────────────────────────
# @app.schedule("every 1h")
# async def hourly():
#     app.log.info("Hourly check")

# @app.schedule("0 9 * * *")
# async def morning():
#     app.log.info("Good morning!")


if __name__ == "__main__":
    app.run()
''',
}


# ── Template entity slots (placeholder → question) ──────────────────────────
# Each template defines which entity slots to ask for.
# Format: (placeholder_entity_id, question_label, domain_filter)

_TEMPLATE_SLOTS: dict[str, list[tuple[str, str, str]]] = {
    "motion": [
        ("binary_sensor.motion_sensor", "Motion sensor", "binary_sensor"),
        ("light.motion_light", "Light to turn on", "light"),
    ],
    "climate": [
        ("sensor.temperature_sensor", "Temperature sensor", "sensor"),
        ("fan.cooling_fan", "Fan or AC", "fan,climate"),
        ("climate.thermostat", "Thermostat", "climate"),
    ],
    "alarm": None,  # special: uses comma-separated list
    "leak": [
        ("binary_sensor.leak_sensor", "Leak sensor", "binary_sensor"),
        ("valve.main_water", "Main water valve", "valve"),
    ],
    "report": [
        ("sensor.temperature_sensor", "Temperature sensor", "sensor"),
        ("sensor.humidity_sensor", "Humidity sensor", "sensor"),
    ],
    "custom": None,  # no entity substitution
}


# ── Commands ────────────────────────────────────────────────────────────────


async def _wizard_discover(url: str, token: str) -> dict[str, str]:
    """Fetch all entities from HA. Returns {entity_id: friendly_name}."""
    from hassreactor.engine import EventEngine

    engine = EventEngine(url, token, verify_ssl=False)
    try:
        await engine.connect()
        states = await engine.get_states()
    finally:
        await engine.disconnect()

    result: dict[str, str] = {}
    for s in states:
        eid = s.get("entity_id", "")
        name = s.get("attributes", {}).get("friendly_name", eid)
        result[eid] = name
    return result


def _print_entity_summary(entities: dict[str, str]) -> None:
    """Print entities grouped by domain."""
    by_domain: dict[str, list[tuple[str, str]]] = {}
    for eid, name in sorted(entities.items()):
        domain = eid.split(".")[0] if "." in eid else "other"
        by_domain.setdefault(domain, []).append((eid, name))

    priority = ["binary_sensor", "sensor", "light",
                "switch", "climate", "cover", "fan", "valve"]
    for domain in priority:
        items = by_domain.pop(domain, [])
        if not items:
            continue
        print(f"   {domain} ({len(items)})")
        for eid, name in items[:5]:
            print(f"     {eid}: {name}")
        if len(items) > 5:
            print(f"     ... and {len(items) - 5} more")
        print()
    for domain, items in sorted(by_domain.items()):
        print(f"   {domain} ({len(items)})")
        for eid, name in items[:3]:
            print(f"     {eid}: {name}")
        if len(items) > 3:
            print(f"     ... and {len(items) - 3} more")
        print()


def _filter_entities(
    entities: dict[str, str], domains: str
) -> dict[str, str]:
    """Filter entities by domain(s), comma-separated."""
    allowed = {d.strip() for d in domains.split(",")}
    return {
        eid: name
        for eid, name in entities.items()
        if eid.split(".")[0] in allowed
    }


def _ask_template_entities(
    tmpl: str, content: str, entities: dict[str, str]
) -> str:
    """Ask user to pick entities for each slot in the template."""
    if tmpl == "alarm":
        return _ask_alarm_entities(content, entities)

    slots = _TEMPLATE_SLOTS.get(tmpl)
    if not slots:
        return content

    for placeholder, question, domain_filter in slots:
        # Show matching entities
        filtered = _filter_entities(entities, domain_filter)
        print(f"   {question} ({domain_filter}):")
        if filtered:
            for i, (eid, name) in enumerate(sorted(filtered.items()), 1):
                print(f"     [{i}] {eid}  ({name})")
            print(f"     [{len(filtered) + 1}] Type manually")
            choice = input("   Pick a number or type entity ID: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(filtered):
                pick = sorted(filtered.items())[int(choice) - 1][0]
            elif choice:
                pick = choice
            else:
                continue
        else:
            print(f"     (no {domain_filter} entities found)")
            pick = input(f"   Enter {question} entity ID: ").strip()
            if not pick:
                continue

        content = content.replace(placeholder, pick)
        print(f"     ✅ Using: {pick}\n")

    return content


def _ask_alarm_entities(
    content: str, entities: dict[str, str]
) -> str:
    """Special handler for alarm template — comma-separated list."""
    filtered = _filter_entities(entities, "binary_sensor")
    print("   Door/window sensors to monitor (binary_sensor):")
    picks: list[str] = []
    if filtered:
        for i, (eid, name) in enumerate(sorted(filtered.items()), 1):
            print(f"     [{i}] {eid}  ({name})")
        print()
        print("   Type numbers (comma-separated, e.g. 1,3,5)")
        print("   or type entity IDs directly")
        raw = input("   > ").strip()
        if raw:
            # Check if all tokens are numbers
            tokens = [t.strip() for t in raw.split(",")]
            sorted_entities = sorted(filtered.items())
            if all(t.isdigit() for t in tokens):
                picks = [
                    sorted_entities[int(t) - 1][0]
                    for t in tokens
                    if 1 <= int(t) <= len(sorted_entities)
                ]
            else:
                picks = [t for t in tokens if "." in t]
            if picks:
                # Replace the DOORS list in the template
                import re
                old_list = re.search(
                    r'DOORS = \[.*?\]', content, re.DOTALL
                )
                if old_list:
                    items = ",\n    ".join(f'"{p}"' for p in picks)
                    new_list = f"DOORS = [\n    {items},\n]"
                    content = content.replace(old_list.group(0), new_list)
    print(f"     ✅ Monitoring {len(picks)} sensors\n")
    return content


def _extract_template_body(content: str) -> str:
    """Extract only the automation functions from a template,
    stripping the Reactor init and 'if __name__' block."""
    # Find the blank line after "app = Reactor(...)"
    marker = "app = Reactor("
    idx = content.find(marker)
    if idx == -1:
        return content
    # Skip to end of the Reactor line
    newline = content.index("\n", idx)
    # Skip trailing blank lines
    start = newline + 1
    while start < len(content) and content[start] == "\n":
        start += 1
    # Find 'if __name__' and remove it + app.run()
    main_idx = content.rfind("if __name__")
    if main_idx != -1:
        # Back up to the blank line before if __name__
        end = main_idx
        while end > start and content[end - 1] == "\n":
            end -= 1
        return content[start:end].rstrip()
    return content[start:].rstrip()


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


def cmd_wizard(ha_url: str, ha_token: str, append: bool = False) -> int:
    """Interactive wizard: credentials → discover → pick entities → generate."""
    import asyncio

    print("\n🔮 hassreactor Wizard\n")
    print("Let's build your automation step by step.\n")

    # ── Phase 1: Get HA credentials ──────────────────────────────────────
    url = ha_url or os.getenv("HA_URL", "")
    token = ha_token or os.getenv("HA_TOKEN", "")

    if append:
        # In append mode, skip credential prompts — read from .env or file
        if url and token:
            pass  # Already from env
        else:
            # Try reading from existing automations.py
            try:
                with open("automations.py", encoding="utf-8") as f:
                    src = f.read()
                import re as _re
                m = _re.search(r'HA_URL\s*=\s*"([^"]*)"', src)
                if m:
                    url = m.group(1)
                m = _re.search(r'HA_TOKEN\s*=\s*"([^"]*)"', src)
                if m:
                    token = m.group(1)
            except FileNotFoundError:
                pass
        if not url or not token:
            print("\n❌ Cannot find HA credentials for discovery.")
            print("   Set HA_URL/HA_TOKEN env vars or run wizard without --append first.")
            return 1
    else:
        if not url:
            url = input(
                "Home Assistant URL [http://homeassistant:8123]: "
            ).strip()
            if not url:
                url = "http://homeassistant:8123"

        if not token:
            print(
                "\nCreate a token in HA:"
                " Settings → People → Long-Lived Access Tokens"
            )
            token = input("Home Assistant token: ").strip()
            if not token:
                print("\n❌ Token is required to connect to Home Assistant.")
                return 1

        # Save to .env for future use
        save = input("\nSave credentials to .env file? [Y/n]: ").strip().lower()
        if save in ("", "y", "yes"):
            with open(".env", "w", encoding="utf-8") as f:
                f.write(f"HA_URL={url}\n")
                f.write(f"HA_TOKEN={token}\n")
            print("   ✅ Saved to .env")

    # ── Phase 2: Discovery (optional) ────────────────────────────────────
    do_disc = input(
        "\nConnect to HA and discover your entities? [Y/n]: "
    ).strip().lower()
    entities: dict[str, str] = {}  # entity_id → friendly_name

    if do_disc in ("", "y", "yes"):
        print("\n   Connecting to Home Assistant...")
        try:
            entities = asyncio.run(_wizard_discover(url, token))
            if entities:
                print(f"\n   ✅ Discovered {len(entities)} entities:\n")
                _print_entity_summary(entities)
            else:
                print("   ⚠️  No entities found.")
        except Exception as e:
            print(f"   ⚠️  Could not connect: {e}")
            print("   Continuing with placeholder entity IDs...\n")

    # ── Phase 3: Category selection ─────────────────────────────────────
    print("\nWhat do you want to automate?")
    print("  [1] Motion sensor → light")
    print("  [2] Temperature → fan/climate")
    print("  [3] Door/window open → notification")
    print("  [4] Water leak → valve + alert")
    print("  [5] Schedule → hourly report")
    print("  [6] Custom (pick your own triggers)")

    choice = input("> ").strip()
    template_map = {
        "1": "motion", "2": "climate", "3": "alarm",
        "4": "leak", "5": "report", "6": "custom",
    }
    if choice not in template_map:
        print("\nInvalid choice.")
        return 1

    tmpl = template_map[choice]
    content = _TEMPLATES[tmpl]

    # Inject real credentials
    content = content.replace(
        'HA_URL = "http://homeassistant:8123"',
        f'HA_URL = "{url}"',
    )
    content = content.replace(
        'HA_TOKEN = "your-long-lived-token-here"',
        f'HA_TOKEN = "{token}"',
    )

    # ── Phase 4: Entity selection ───────────────────────────────────────
    if entities and tmpl != "custom":
        print()
        content = _ask_template_entities(tmpl, content, entities)

    # ── Phase 5: Generate ────────────────────────────────────────────────
    path = "automations.py"

    if append:
        if not os.path.exists(path):
            print(f"\n❌ {path} not found. Run 'hassreactor wizard' first.")
            return 1
        # Extract only the functions from the template
        body = _extract_template_body(content)
        if not body.strip():
            print("\n❌ Nothing to append.")
            return 1
        # Read existing file, find 'if __name__', insert before it
        with open(path, encoding="utf-8") as f:
            existing = f.read()
        main_marker = "if __name__"
        idx = existing.rfind(main_marker)
        if idx == -1:
            print(f"\n❌ {path} is missing 'if __name__' block.")
            return 1
        # Insert new functions before if __name__, with blank lines
        new_content = (
            existing[:idx].rstrip()
            + "\n\n" + body + "\n\n\n"
            + existing[idx:]
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"\n✅ Appended to {path}")
        print(f"   Run: python {path}")
        return 0

    if os.path.exists(path):
        overwrite = input(
            f"\n{path} already exists. Overwrite? [y/N]: "
        ).strip().lower()
        if overwrite not in ("y", "yes"):
            print("Aborted.")
            return 0

    os.makedirs(".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n✅ Created {path}")
    print(f"   Run: python {path}")
    return 0


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
    wiz_p.add_argument(
        "--append", action="store_true",
        help="Add automations to existing automations.py"
    )

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
        sys.exit(cmd_wizard(args.url, args.token, args.append))
    elif args.command == "discover":
        sys.exit(cmd_discover())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
