from reacthass import Reactor

# reacthass settings
token = 'YOUR TOKEN'
hassurl = 'HOME ASSISTANT URL'

# Initiate reacthass session
hass = Reactor(hassurl, token, cache_refresh_seconds=2, verify_ssl=False)  # refresh every 2 seconds for fast response


def main():
    while True:
        light = 'light.bathroom'
        motion = 'binary_sensor.presence'
        person = 'person.josh'
        check = hass.if_state_equal_to_value(motion, 'on')
        light_state = hass.get_entity_state(light)
        light_domain = hass.get_domain('light')

        if check and light_state == 'off':
            if hass.get_entity_state(person) == 'home':
                light_domain.turn_on(light)
        elif not check and light_state == 'on':
            light_domain.turn_off(light)


if __name__ == '__main':
    main()
