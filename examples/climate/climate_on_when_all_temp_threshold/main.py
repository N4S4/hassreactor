from reacthass import Reactor
from time import sleep

# reacthass settings
token = 'YOUR TOKEN'
hassurl = 'HOME ASSISTANT URL'

# Initiate reacthass session
hass = Reactor(hassurl, token, verify_ssl=False)


def main():
    while True:
        climates = hass.get_entities_name('climate')
        room1 = float(hass.get_entity_state('sensor.temperature_1'))
        room2 = float(hass.get_entity_state('sensor.temperature_2'))
        room3 = float(hass.get_entity_state('sensor.temperature_3'))

        if room1 <= 18 and room2 <= 18 and room3 <= 18:
            entity = hass.get_domain('climate')
            for climate_entity_id in climates:
                entity.turn_on(entity_id=climate_entity_id)


if __name__ == '__main__':
    main()
