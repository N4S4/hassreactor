# hassreactor

Event-driven Home Assistant automations in Python. No YAML, no Node-RED, no AppDaemon — just Python.

## Why

Home Assistant has a powerful automation engine, but it lives in YAML or a UI. Sometimes you just want to write a Python script:

- "If living room temp > 28°C, turn on fan"
- "If front door opens for more than 5 minutes, send me a Telegram message"
- "Every hour, log the temperature"
- "React to any HA event, not just state changes"

hassreactor lets you write these as plain Python files using WebSocket events — no polling, no complex setup.

## Install

```bash
pip install hassreactor
```

## Quick Start (for Python users)

```bash
pip install hassreactor
hassreactor init               # generates automations.py
```

Open `automations.py` and replace the two placeholders at the top:

```python
HA_URL = "http://your-ha-ip:8123"
HA_TOKEN = "your-long-lived-token-here"   # Settings → People → Long-Lived Access Tokens
```

Then run it:

```bash
python automations.py
```

You should see `Connected to Home Assistant` — your automations are now live.

> **No Python?** Skip this and use [`hassreactor wizard`](#wizard-no-python-required) instead — it asks for credentials interactively and lets you pick entities from a menu.

## Wizard (no Python required)

If you don't know Python, the wizard builds your automation step by step — it asks for credentials, discovers your entities, lets you pick them by number, and generates a ready-to-run `automations.py`:

```bash
hassreactor wizard
```

The wizard walks you through:

1. **Credentials** — asks for HA URL and token (saves to `.env` for future use)
2. **Discovery** (optional) — connects to HA and shows your actual entities grouped by type
3. **Category** — pick what you want to automate:
   - [1] Motion sensor → light
   - [2] Temperature → fan/climate
   - [3] Door/window → notification
   - [4] Water leak → valve + alert
   - [5] Schedule → hourly report
   - [6] Custom (all trigger types as comments)
4. **Pick entities** — for each entity your automation needs, the wizard shows a numbered list of matching entities from your HA (e.g. *Pick a number or type entity ID*)
5. **Generate** — writes `automations.py` with your real entity IDs and credentials, ready to run

No more editing placeholder entity IDs by hand.

Need to see what entities you have without using the wizard? Run:

```bash
hassreactor discover
```

This connects to Home Assistant and lists all your entities grouped by type, with suggestions on how to automate them.

### Wizard + Docker

The wizard runs **locally** — it's an interactive tool that asks questions in your terminal. It does **not** work inside Docker.

The workflow is:

```bash
# 1. On your PC: run the wizard (credentials + entity discovery + generate)
hassreactor wizard

# 2. Start Docker (mounts your automations.py as a volume)
docker compose up -d
```

Once running, edit `automations.py` anytime, save — hassreactor hot-reloads inside the container without restarting.

### Adding more automations

Already have `automations.py` and want to add another automation? Use the wizard in append mode:

```bash
hassreactor wizard --append
```

This skips the credential prompt (reads from your existing file), runs optional discovery, and inserts the new automation functions into your existing `automations.py` — nothing gets overwritten.

### Templates

Skip the wizard and generate directly from a named template:

```bash
hassreactor init --template motion    # motion sensor → light
hassreactor init --template climate   # temperature → fan/climate
hassreactor init --template alarm     # door/window → notification
hassreactor init --template leak      # water leak → valve + alert
```

## Trigger Types

| Trigger | Description |
|---|---|
| `@app.when(entity, above=N)` | Numeric value crosses ABOVE threshold |
| `@app.when(entity, below=N)` | Numeric value crosses BELOW threshold |
| `@app.when(entity, to="on")` | State changes TO an exact value |
| `@app.when(entity, changes=True)` | ANY state change |
| `@app.on("call_service")` | React to generic HA events |
| `@app.on("automation_triggered")` | Any event type |
| `@app.schedule("every 30m")` | Run every 30 minutes |
| `@app.schedule("every 2h")` | Run every 2 hours |
| `@app.schedule("0 9 * * *")` | Cron expression (every day at 9am) |

## Advanced Triggers

```python
# Debounce — wait 2s after last event before firing
@app.when("sensor.motion", to="on", within="2s")
async def motion_debounced(event):
    ...

# Throttle — fire at most once per 30 seconds
@app.when("sensor.temp", changes=True, throttle="30s")
async def temp_throttled(event):
    ...

# Duration — state must persist for N seconds
@app.when("binary_sensor.door", to="on", for_="5m")
async def door_open_too_long(event):
    await app.notify.telegram(message="Door open for 5 minutes!")
```

## Generic Events

React to any Home Assistant event, not just `state_changed`:

```python
@app.on("call_service")
async def debug_service(event):
    app.log.info("Service called: %s", event.event_type)

@app.on("automation_triggered")
async def on_automation(event):
    app.log.info("Automation fired: %s", event.event_type)
```

## Persistent Store

Share state across triggers:

```python
@app.when("sensor.clicks", changes=True)
async def count_clicks(event):
    app.store["clicks"] = app.store.get("clicks", 0) + 1

@app.schedule("every 1h")
async def report():
    clicks = app.store.get("clicks", 0)
    app.log.info("Clicks this hour: %d", clicks)
    app.store["clicks"] = 0  # reset
```

## Auto-Reconnect

If Home Assistant restarts or the network drops, hassreactor reconnects automatically with exponential backoff (1s → 2s → 4s → ... → 60s max). No data loss — all triggers re-register on reconnect.

## Calling Services

Any HA service is available as a method on the domain:

```python
await app.light.turn_on(entity_id="light.kitchen", brightness=128)
await app.climate.set_temperature(entity_id="climate.home", temperature=22)
await app.switch.toggle(entity_id="switch.pump")
await app.notify.telegram(message="Hello!")
```

## How It Works

hassreactor connects to Home Assistant via **WebSocket** and subscribes to events. When an entity you're watching changes state, your function runs instantly — no polling, no sleep loops.

Service calls use the REST API. Only dependency: `aiohttp`.

## Docker

```bash
cp .env.example .env                    # set your HA_TOKEN
docker compose up -d                    # build and start
```

Your `automations.py` lives **on your PC** and is mounted as a volume — not inside the image:

```yaml
volumes:
  - ./automations.py:/app/automations.py   # file on your host
```

Edit `automations.py`, save, and **the container never restarts**:
hassreactor hot-reloads the module, detaches old triggers and
re-registers new ones. The WebSocket connection to HA stays alive.

If Home Assistant runs on the Docker host, use `network_mode: host` or
the LAN IP (not `localhost`).

## License

MIT
