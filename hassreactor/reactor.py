"""
Reactor — the main entry point for hassreactor.

Ties together the WebSocket engine, service proxy, and scheduler
into a single, ergonomic interface for writing Home Assistant
automations in Python.
"""
from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any, Callable, Awaitable

from .domain_proxy import DomainProxy
from .engine import EventEngine
from .scheduler import Scheduler


class TriggerEvent:
    """Event passed to @app.when callbacks."""

    def __init__(self, engine: EventEngine, event_data: dict):
        self.entity_id: str = event_data.get("entity_id", "")
        self.old_state: dict | None = event_data.get("old_state")
        self.new_state: dict | None = event_data.get("new_state")

        # Convenience: new state value as string
        ns = self.new_state or {}
        self.state: str = ns.get("state", "")
        self.attributes: dict = ns.get("attributes", {})

    def __repr__(self) -> str:
        return (
            f"TriggerEvent(entity_id={self.entity_id!r}, "
            f"state={self.state!r})"
        )


class Reactor:
    """Main application class for hassreactor.

    Usage::

        app = Reactor("http://ha:8123", "token")

        @app.when("sensor.temp", above=28)
        async def hot(event):
            await app.fan.turn_on(entity_id="fan.ventilatore")

        if __name__ == "__main__":
            app.run()
    """

    def __init__(
        self,
        url: str,
        token: str,
        verify_ssl: bool = True,
    ):
        self._engine = EventEngine(url, token, verify_ssl=verify_ssl)
        self._proxy = DomainProxy(self._engine)
        self._scheduler = Scheduler()
        self._triggers: list[tuple[str, dict, Callable]] = []
        self._running = False
        self.log = logging.getLogger("hassreactor")

    # -- domain access ---------------------------------------------------------

    def __getattr__(self, name: str):
        """Proxy unknown attrs to the domain proxy.

        Example: app.light → DomainProxy(engine).light
        """
        if name.startswith("_"):
            raise AttributeError(name)
        # Check if it's a known domain or delegate to proxy
        return getattr(self._proxy, name)

    # -- decorators -----------------------------------------------------------

    def when(
        self,
        entity_id: str,
        *,
        above: float | None = None,
        below: float | None = None,
        to: str | None = None,
        changes: bool = False,
    ):
        """Decorator: trigger on state changes.

        Args:
            entity_id: HA entity to watch (e.g. 'sensor.temp')
            above: Fire when numeric state goes ABOVE this value
            below: Fire when numeric state goes BELOW this value
            to: Fire when state changes TO this exact value
            changes: Fire on ANY state change

        Example::

            @app.when("sensor.temp", above=28)
            async def hot(event):
                await app.fan.turn_on(entity_id="fan.ventilatore")
        """
        conditions = {}
        if above is not None:
            conditions["above"] = above
        if below is not None:
            conditions["below"] = below
        if to is not None:
            conditions["to"] = to
        if changes:
            conditions["changes"] = True

        def decorator(fn: Callable):
            self._triggers.append((entity_id, conditions, fn))
            return fn

        return decorator

    def schedule(self, expression: str):
        """Decorator: run on a schedule.

        Args:
            expression: "every 30m", "every 2h", or "0 9 * * *"

        Example::

            @app.schedule("every 1h")
            async def report():
                temp = await app.get_state("sensor.temp")
                app.log.info("Temp: %s", temp)
        """

        def decorator(fn: Callable):
            self._scheduler.add(expression, fn)
            return fn

        return decorator

    # -- state access ----------------------------------------------------------

    async def get_state(self, entity_id: str) -> str | None:
        """Get current state value of an entity."""
        s = await self._engine.get_state(entity_id)
        if s:
            return s.get("state")
        return None

    async def get_states(self) -> list[dict]:
        """Get all entity states."""
        return await self._engine.get_states()

    # -- lifecycle ------------------------------------------------------------

    def run(self) -> None:
        """Start the reactor (blocking)."""
        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            self.log.info("Shutting down...")

    async def start(self) -> None:
        """Start the reactor (non-blocking). Call from async context."""
        await self._connect()

    async def stop(self) -> None:
        """Stop the reactor."""
        await self._shutdown()

    # -- internal -------------------------------------------------------------

    async def _run(self) -> None:
        await self._connect()

        # Keep alive until signal
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass  # Windows

        try:
            await stop_event.wait()
        finally:
            await self._shutdown()

    async def _connect(self) -> None:
        await self._engine.connect()

        # Register all triggers
        for entity_id, conditions, fn in self._triggers:
            self._engine.on_state_change(
                entity_id,
                self._make_listener(entity_id, conditions, fn),
            )

        self._running = True
        self.log.info("Reactor running — %d triggers active", len(self._triggers))

    def _make_listener(
        self, entity_id: str, conditions: dict, fn: Callable,
    ):
        """Build a closure that filters events and calls the user function."""

        async def listener(data: dict):
            event = TriggerEvent(self._engine, data)

            # Check conditions
            if not conditions:
                return  # Should not happen

            # "changes" — fire on any state change
            if conditions.get("changes"):
                await fn(event)
                return

            new_state = data.get("new_state")
            if not new_state:
                return

            state_val = new_state.get("state", "")

            # "to" — exact state match
            if "to" in conditions:
                if state_val == conditions["to"]:
                    await fn(event)
                return

            # "above" / "below" — numeric comparisons
            try:
                num_val = float(state_val)
            except (TypeError, ValueError):
                return

            if "above" in conditions:
                old_state = data.get("old_state") or {}
                old_val = old_state.get("state", "")
                try:
                    old_num = float(old_val)
                except (TypeError, ValueError):
                    old_num = float("-inf")
                # Fire only on crossing the threshold (not every poll while above)
                if num_val > conditions["above"] and old_num <= conditions["above"]:
                    await fn(event)

            if "below" in conditions:
                old_state = data.get("old_state") or {}
                old_val = old_state.get("state", "")
                try:
                    old_num = float(old_val)
                except (TypeError, ValueError):
                    old_num = float("inf")
                if num_val < conditions["below"] and old_num >= conditions["below"]:
                    await fn(event)

        return listener

    async def _shutdown(self) -> None:
        self._running = False
        self._scheduler.cancel_all()
        await self._engine.disconnect()
        self.log.info("Reactor stopped")
