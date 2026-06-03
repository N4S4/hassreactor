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

## Quick Start

```bash
hassreactor init          # create automations.py
# edit HA_URL, HA_TOKEN, then:
python automations.py
```

Or set env vars and skip config entirely:

```bash
export HA_URL=http://homeassistant:8123
export HA_TOKEN=your-long-lived-token
hassreactor init
python automations.py
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
