from reacthass import Reactor
from time import sleep

# reacthass settings
token = 'YOUR TOKEN'
hassurl = 'HOME ASSISTANT URL'

# Initiate reacthass session
hass = Reactor(hassurl, token, verify_ssl=False)


def main():
    while True:
        power_load = float(hass.get_entity_state('sensor.power'))
        users = [
            'switch.oven',
            'switch.heater_room',
            'switch.heater_kids',
            'switch.water_heater',
            'switch.fan',
        ]

        if power_load >= 4000:
            domain = hass.get_domain('switch')
            for entity_id in users:
                if hass.get_entity_state(entity_id) == 'on':
                    domain.turn_off(entity_id)
        sleep(1)


if __name__ == '__main__':
    main()
