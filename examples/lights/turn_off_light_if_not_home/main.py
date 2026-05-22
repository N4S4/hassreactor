from reacthass import Reactor
from time import sleep

# reacthass settings
token = 'YOUR TOKEN'
hassurl = 'HOME ASSISTANT URL'

# Initiate reacthass session
hass = Reactor(hassurl, token, verify_ssl=False)


def main():
    while True:
        person = 'person.renato'
        if hass.if_state_equal_to_value(person, 'not_home'):
            lights_on = hass.check_specific_state_in_group('light', 'on')
            domain = hass.get_domain('light')
            for entity_id in lights_on:
                domain.turn_off(entity_id)
        sleep(60 * 5)


if __name__ == '__main':
    main()
