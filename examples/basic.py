"""
Example: temperature-controlled fan + door alert + hourly report.

Copy this file, edit the URL and token, run it.
"""
from hassreactor import Reactor

# ── Configuration ──
HA_URL = "http://homeassistant:8123"
HA_TOKEN = "your-long-lived-token-here"


app = Reactor(HA_URL, HA_TOKEN)


# ── Automations ──

@app.when("sensor.temperatura_salotto", above=28)
async def accendi_ventilatore(event):
    """If temp goes above 28°C, turn on the fan."""
    app.log.info("Temperature crossed 28°C — turning on fan")
    await app.fan.turn_on(entity_id="fan.ventilatore")


@app.when("sensor.temperatura_salotto", below=25)
async def spegni_ventilatore(event):
    """If temp drops below 25°C, turn off the fan."""
    app.log.info("Temperature dropped below 25°C — turning off fan")
    await app.fan.turn_off(entity_id="fan.ventilatore")


@app.when("binary_sensor.porta_ingresso", to="on")
async def porta_aperta(event):
    """Alert when front door opens."""
    app.log.info("Front door opened!")
    await app.notify.telegram(message="🚪 Porta d'ingresso aperta!")


@app.schedule("every 1h")
async def report():
    """Hourly temperature report."""
    temp = await app.get_state("sensor.temperatura_salotto")
    app.log.info("Hourly report — temperature: %s°C", temp)


# ── Run ──

if __name__ == "__main__":
    app.run()
