# hassreactor

Event-driven Home Assistant automations in Python. No YAML, no Node-RED, no AppDaemon — just Python.

## Why

Home Assistant has a powerful automation engine, but it lives in YAML or a UI. Sometimes you just want to write a Python script:

- "If living room temp > 28°C, turn on fan"
- "If front door opens, send me a Telegram message"
- "Every hour, log the temperature"

hassreactor lets you write these as plain Python files using WebSocket events — no polling, no complex setup.

## Install

```bash
pip install hassreactor
```

## Quick Start

Create a file `automations.py`:

```python
from hassreactor import Reactor

app = Reactor("http://homeassistant:8123", "your-long-lived-token")

@app.when("sensor.temperatura_salotto", above=28)
async def accendi_ventilatore(event):
    """When temp goes above 28°C, turn on the fan."""
    await app.fan.turn_on(entity_id="fan.ventilatore")

@app.when("binary_sensor.porta_ingresso", to="on")
async def porta_aperta(event):
    """When front door opens, notify."""
    await app.notify.telegram(message="Porta d'ingresso aperta!")

@app.schedule("every 1h")
async def report():
    temp = await app.get_state("sensor.temperatura_salotto")
    print(f"Current temperature: {temp}°C")

if __name__ == "__main__":
    app.run()
```

Run it:

```bash
python automations.py
```

## Trigger Types

| Trigger | Description |
|---|---|
| `@app.when(entity, above=N)` | Numeric value crosses ABOVE threshold |
| `@app.when(entity, below=N)` | Numeric value crosses BELOW threshold |
| `@app.when(entity, to="on")` | State changes TO an exact value |
| `@app.when(entity, changes=True)` | ANY state change |
| `@app.schedule("every 30m")` | Run every 30 minutes |
| `@app.schedule("every 2h")` | Run every 2 hours |
| `@app.schedule("0 9 * * *")` | Cron expression (every day at 9am) |

## Calling Services

Any HA service is available as a method on the domain:

```python
await app.light.turn_on(entity_id="light.kitchen", brightness=128)
await app.climate.set_temperature(entity_id="climate.home", temperature=22)
await app.switch.toggle(entity_id="switch.pump")
await app.notify.telegram(message="Hello!")
```

## How It Works

hassreactor connects to Home Assistant via **WebSocket** and subscribes to `state_changed` events. When an entity you're watching changes state, your function runs instantly — no polling, no sleep loops.

Service calls use the REST API.

Only dependency: `aiohttp`.

## License

MIT — same as the original reacthass project.
