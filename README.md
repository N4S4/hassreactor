# ReactHass

ReactHass is a tiny Home Assistant helper around `homeassistant_api`.

## Install

`pip install reacthass`

## Usage
```python
from reacthass import Reactor

hass = Reactor('HOME ASSISTANT URL', 'YOUR TOKEN')

if hass.when_value_reached('sensor.temperature', 30, value_type='number'):
    hass.get_domain('fan').turn_on(entity_id='fan.fan')
```

## Notes
- Home Assistant states are strings, so numeric checks use `value_type='number'`.
- `get_entities_name('light')` returns full entity IDs like `light.kitchen`.
- The async API mirrors the sync API.

## Persistence
If you want to keep the sensor record in the database you might add to your configuration.yaml:

```yaml
recorder:
  include:
    entities:
      - sensor.test
```

## Examples
See the `/examples` folder.

## Credits
This package is built on top of [HomeAssistantAPI](https://github.com/GrandMoff100/HomeAssistantAPI)
