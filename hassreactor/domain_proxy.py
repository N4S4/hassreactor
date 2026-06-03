"""
Domain proxy for fluent service calls.

Provides `app.light.turn_on(...)` style API by dynamically
generating proxy objects for each Home Assistant domain.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import EventEngine


class _DomainProxy:
    """Proxy for a single HA domain (light, switch, climate, etc.).

    Service calls become method calls:
        app.light.turn_on(entity_id='light.kitchen')
    """

    def __init__(self, engine: "EventEngine", domain: str):
        self._engine = engine
        self._domain = domain

    def __getattr__(self, service: str):
        """Return a callable that invokes the service."""
        if service.startswith("_"):
            raise AttributeError(service)

        async def _call(**kwargs):
            data = {k: v for k, v in kwargs.items() if k not in ("entity_id",)}
            target = None
            if "entity_id" in kwargs:
                target = {"entity_id": kwargs["entity_id"]}
            return await self._engine.call_service(
                self._domain, service, data=data, target=target
            )

        return _call

    def __dir__(self):
        return []  # Dynamic — auto-complete not supported


class DomainProxy:
    """Top-level proxy that returns _DomainProxy instances.

    Usage:
        app = DomainProxy(engine)
        await app.light.turn_on(entity_id='light.kitchen')
        await app.climate.set_temperature(entity_id='climate.home', temperature=22)
    """

    def __init__(self, engine: "EventEngine"):
        self._engine = engine
        self._cache: dict[str, _DomainProxy] = {}

    def __getattr__(self, domain: str) -> _DomainProxy:
        if domain.startswith("_"):
            raise AttributeError(domain)
        if domain not in self._cache:
            self._cache[domain] = _DomainProxy(self._engine, domain)
        return self._cache[domain]

    def __getitem__(self, domain: str) -> _DomainProxy:
        return self.__getattr__(domain)
