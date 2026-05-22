import asyncio
from datetime import timedelta
import logging
from typing import Any, Optional

from aiohttp_client_cache import CachedSession, FileBackend
from homeassistant_api import Client, State

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class AsyncReactor(Client):
    def __init__(self, url, token, cache_refresh_seconds=30, verify_ssl=False):
        self._verify_ssl = verify_ssl
        self._token = token
        self._url = url if url.endswith('/api') else f'{url}/api'

        self._cache_refresh_seconds = CachedSession(
            cache=FileBackend(expire_after=timedelta(seconds=cache_refresh_seconds))
        )

        super().__init__(
            self._url,
            self._token,
            async_cache_session=self._cache_refresh_seconds,
            verify_ssl=self._verify_ssl,
            use_async=True,
        )

    async def get_groups(self):
        return list((await self.async_get_entities()).keys())

    async def send_value_to_entity(self, entity: str, value: Any, attributes: Optional[dict] = None):
        state = State(state=value, entity_id=entity, attributes=attributes or {})
        await self.async_set_state(state)

    async def get_entities_name(self, group: str):
        entities = await self.async_get_entities()
        entity_group = entities.get(group)
        if entity_group is None:
            return []
        return list(entity_group.entities.keys())

    async def get_entity_state(self, entity_id):
        state = await self.async_get_state(entity_id=entity_id)
        return state.state

    async def get_services(self, domain: str):
        return await self.async_get_domain(domain)

    async def check_specific_state_in_group(self, group: str, state: Any) -> dict:
        all_states = await self.async_get_states()
        group_states = {}
        for entity in all_states:
            if str(entity.entity_id).startswith(f'{group}.') and entity.state == state:
                group_states[entity.entity_id] = entity.state
        return group_states

    async def if_state_equal_to_value(self, entity: str, threshold_value: Any, value_type: str = 'string',
                                      operator_type: str = '=='):
        state = await self.get_entity_state(entity)

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

    async def when_value_reached(self, client, entity: str, threshold_value: Any, value_type: str = 'string',
                                 operator_type: str = '==', poll_interval: float = 1.0,
                                 timeout: Optional[float] = None):
        start = asyncio.get_event_loop().time()
        watcher = client or self
        while True:
            if await watcher.if_state_equal_to_value(entity, threshold_value, value_type, operator_type):
                return True
            if timeout is not None and (asyncio.get_event_loop().time() - start) >= timeout:
                return False
            await asyncio.sleep(poll_interval)
