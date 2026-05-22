from datetime import timedelta
import logging
import time
from typing import Any, Optional

from homeassistant_api import Client, State
from requests_cache import CachedSession

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class Reactor(Client):
    def __init__(self, url: str, token: str,
                 cache_refresh_seconds: int = 30, verify_ssl: bool = True):
        """The lower cache_refresh_seconds is, the more requests are made."""

        self._cache_refresh_seconds = CachedSession(
            backend='filesystem',
            expire_after=timedelta(seconds=cache_refresh_seconds),
        )

        self._verify_ssl = verify_ssl
        self._url = url if url.endswith('/api') else f'{url}/api'

        super().__init__(
            self._url,
            token,
            cache_session=self._cache_refresh_seconds,
            verify_ssl=self._verify_ssl,
            use_async=False,
        )

        self._entity_group = self.get_entities()
        self._base_url = url
        self._token = token

    def send_value_to_entity(self, entity: str, value: Any, attributes: Optional[dict] = None):
        state = State(state=value, entity_id=entity, attributes=attributes or {})
        return self.set_state(state)

    def get_groups(self):
        return list(self._entity_group.keys())

    def get_entities_name(self, group: str):
        entity_group = self._entity_group.get(group)
        if entity_group is None:
            return []
        return list(entity_group.entities.keys())

    def get_entity_state(self, entity: str):
        state = self.get_entity(entity_id=entity).state.state
        return state

    def get_services(self, domain: str):
        return self.get_domain(domain)

    def check_specific_state_in_group(self, group: str, state: Any) -> dict:
        all_states = self.get_states()
        group_states = {}
        for entity in all_states:
            if str(entity.entity_id).startswith(f'{group}.') and entity.state == state:
                group_states[entity.entity_id] = entity.state
        return group_states

    def if_state_equal_to_value(self, entity: str, threshold_value: Any, value_type: str = 'string',
                                operator_type: str = '=='):
        state = self.get_entity_state(entity)

        if value_type == 'string':
            state = str(state)
            threshold_value = str(threshold_value)
        elif value_type == 'number':
            try:
                state = float(state)
                threshold_value = float(threshold_value)
            except (TypeError, ValueError):
                return False
        else:
            return False

        if operator_type == '==':
            return state == threshold_value
        if operator_type == '>=':
            return state >= threshold_value
        if operator_type == '<=':
            return state <= threshold_value
        if operator_type == '<':
            return state < threshold_value
        if operator_type == '>':
            return state > threshold_value
        if operator_type == '!=':
            return state != threshold_value
        return False

    def when_value_reached(self, entity: str, threshold_value: Any, value_type: str = 'string',
                           operator_type: str = '==', poll_interval: float = 1.0,
                           timeout: Optional[float] = None):
        start = time.monotonic()
        while True:
            if self.if_state_equal_to_value(entity, threshold_value, value_type, operator_type):
                return True
            if timeout is not None and (time.monotonic() - start) >= timeout:
                return False
            time.sleep(poll_interval)
