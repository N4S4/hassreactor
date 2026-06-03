"""
Reactor — the main entry point for hassreactor.

Ties together the WebSocket engine, service proxy, and scheduler
into a single, ergonomic interface for writing Home Assistant
automations in Python.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from typing import Any, Callable, Awaitable

from .domain_proxy import DomainProxy
from .engine import EventEngine
from .scheduler import Scheduler


class TriggerEvent:
    """Event passed to @app.when and @app.on callbacks."""

    def __init__(self, event_data: dict, engine: EventEngine | None = None):
        self._engine = engine

        # Entity-level fields (state_changed)
        data = event_data.get("data", event_data)
        self.entity_id: str = data.get("entity_id", "")
        self.old_state: dict | None = data.get("old_state")
        self.new_state: dict | None = data.get("new_state")

        # Generic event fields
        self.event_type: str = event_data.get("event_type", "")
        self.origin: str = event_data.get("origin", "")
        self.time_fired: str = event_data.get("time_fired", "")

        # Convenience: new state value as string
        ns = self.new_state or {}
        self.state: str = ns.get("state", "")
        self.attributes: dict = ns.get("attributes", {})

    def __repr__(self) -> str:
        return (
            f"TriggerEvent(entity_id={self.entity_id!r}, "
            f"state={self.state!r}, event_type={self.event_type!r})"
        )


class Reactor:
    """Main application class for hassreactor.

    Usage::

        app = Reactor()          # reads HA_URL, HA_TOKEN from env

        @app.when("sensor.temp", above=28, within="5s")
        async def hot(event):
            await app.fan.turn_on(entity_id="fan.ventilatore")

        @app.on("call_service")
        async def on_service(event):
            app.log.info("Service called: %s", event.event_type)

        if __name__ == "__main__":
            app.run()
    """

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        verify_ssl: bool = True,
        auto_reconnect: bool = True,
    ):
        url = url or os.getenv("HA_URL", "")
        token = token or os.getenv("HA_TOKEN", "")
        if not url:
            raise ValueError(
                "HA_URL not set. Pass it explicitly or set the env var."
            )
        if not token:
            raise ValueError(
                "HA_TOKEN not set. Pass it explicitly or set the env var."
            )

        self._engine = EventEngine(
            url, token, verify_ssl=verify_ssl, auto_reconnect=auto_reconnect
        )
        self._proxy = DomainProxy(self._engine)
        self._scheduler = Scheduler()
        self._triggers: list[tuple[str, dict, Callable]] = []  # (entity_id, conditions, fn)
        self._running = False

        # Re-register entity listeners on reconnect
        self._engine.on_reconnect(self._on_reconnect)

        self.log = logging.getLogger("hassreactor")

        # Persistent key-value store (survives reload, shared across triggers)
        self.store: dict[str, Any] = {}

        # State for within / throttle / for_
        self._last_fired: dict[str, float] = {}
        self._pending_delays: dict[str, asyncio.Task] = {}

    # -- domain access ---------------------------------------------------------

    def __getattr__(self, name: str):
        """Proxy unknown attrs to the domain proxy.

        Example: app.light → DomainProxy(engine).light
        """
        if name.startswith("_"):
            raise AttributeError(name)
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
        within: str | None = None,
        throttle: str | None = None,
        for_: str | None = None,
    ):
        """Decorator: trigger on state changes.

        Args:
            entity_id: HA entity to watch (e.g. 'sensor.temp')
            above: Fire when numeric state crosses ABOVE this value
            below: Fire when numeric state crosses BELOW this value
            to: Fire when state changes TO this exact value
            changes: Fire on ANY state change
            within: Debounce — delay fire by N seconds; if another event
                    arrives for the same entity, reset the timer
                    (e.g. "2s", "500ms")
            throttle: Rate-limit — fire at most once per N seconds
                      (e.g. "10s")
            for_: Duration — the state must remain for N seconds
                  before firing (e.g. "5m")

        Example::

            @app.when("sensor.temp", above=28, within="5s")
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
        if within is not None:
            conditions["within"] = _parse_duration_seconds(within)
        if throttle is not None:
            conditions["throttle"] = _parse_duration_seconds(throttle)
        if for_ is not None:
            conditions["for_"] = _parse_duration_seconds(for_)

        def decorator(fn: Callable):
            self._triggers.append((entity_id, conditions, fn))
            return fn

        return decorator

    def on(self, event_type: str):
        """Decorator: react to any Home Assistant event.

        Args:
            event_type: HA event type (e.g. 'call_service',
                        'automation_triggered', 'component_loaded')

        Example::

            @app.on("call_service")
            async def debug_service(event):
                app.log.info("Service: %s", event.event_type)
        """

        def decorator(fn: Callable):
            self._engine.on_event(event_type, fn)
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

        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass

        try:
            await stop_event.wait()
        finally:
            await self._shutdown()

    async def _on_reconnect(self) -> None:
        """Re-register entity listeners after reconnect."""
        for entity_id, _, _ in self._triggers:
            # Re-register with engine (callbacks persist in _triggers)
            self.log.debug("Re-registered listener for %s", entity_id)

    async def _connect(self) -> None:
        await self._engine.connect()

        # Register all triggers (entity-level, with conditions)
        for entity_id, conditions, fn in self._triggers:
            self._engine.on_state_change(
                entity_id,
                self._make_listener(entity_id, conditions, fn),
            )

        self._running = True
        self.log.info(
            "Reactor running — %d triggers, %d schedule tasks",
            len(self._triggers),
            len(self._scheduler._tasks),
        )

    def _make_listener(
        self, entity_id: str, conditions: dict, fn: Callable,
    ):
        """Build a closure that filters events and calls the user function."""

        within_s = conditions.get("within")
        throttle_s = conditions.get("throttle")
        for_s = conditions.get("for_")

        async def listener(data: dict):
            event = TriggerEvent(data)

            if not conditions:
                return

            # "for_" — wait for state to persist
            if for_s is not None:
                new_state = data.get("new_state")
                if not new_state:
                    return
                state_val = new_state.get("state", "")
                if not self._condition_matches(conditions, data):
                    # State changed away from condition — cancel pending
                    task = self._pending_delays.pop(entity_id, None)
                    if task:
                        task.cancel()
                    return
                # Condition met — schedule delayed fire
                key = entity_id
                if key in self._pending_delays:
                    # Already waiting — reset is implicit (state stayed)
                    return
                self._pending_delays[key] = asyncio.create_task(
                    self._fire_after_delay(key, fn, event, for_s)
                )
                return
            else:
                # Cancel any pending for_ on this entity
                for key in list(self._pending_delays):
                    if key.startswith(entity_id):
                        task = self._pending_delays.pop(key, None)
                        if task:
                            task.cancel()

            if not self._condition_matches(conditions, data):
                return

            # "within" — debounce
            if within_s is not None:
                key = f"within:{entity_id}"
                if key in self._pending_delays:
                    self._pending_delays[key].cancel()
                self._pending_delays[key] = asyncio.create_task(
                    self._fire_after_delay(key, fn, event, within_s)
                )
                return

            # "throttle" — rate limit
            if throttle_s is not None:
                key = f"throttle:{entity_id}"
                now = time.monotonic()
                last = self._last_fired.get(key, 0)
                if now - last < throttle_s:
                    return
                self._last_fired[key] = now

            await fn(event)

        return listener

    async def _fire_after_delay(
        self, key: str, fn: Callable, event: TriggerEvent, delay: float,
    ) -> None:
        """Fire a callback after a delay (used by within and for_)."""
        try:
            await asyncio.sleep(delay)
            await fn(event)
        except asyncio.CancelledError:
            pass
        finally:
            self._pending_delays.pop(key, None)

    def _condition_matches(self, conditions: dict, data: dict) -> bool:
        """Check if event data matches the trigger conditions."""
        if not conditions:
            return False

        # "changes" — fire on any state change
        if conditions.get("changes"):
            return True

        new_state = data.get("new_state")
        if not new_state:
            return False

        state_val = new_state.get("state", "")

        # "to" — exact state match
        if "to" in conditions:
            return state_val == conditions["to"]

        # "above" / "below" — numeric comparisons (crossing only)
        try:
            num_val = float(state_val)
        except (TypeError, ValueError):
            return False

        old_state = data.get("old_state") or {}
        old_val = old_state.get("state", "")

        if "above" in conditions:
            try:
                old_num = float(old_val)
            except (TypeError, ValueError):
                old_num = float("-inf")
            return num_val > conditions["above"] and old_num <= conditions["above"]

        if "below" in conditions:
            try:
                old_num = float(old_val)
            except (TypeError, ValueError):
                old_num = float("inf")
            return num_val < conditions["below"] and old_num >= conditions["below"]

        return False

    async def _shutdown(self) -> None:
        self._running = False
        self._scheduler.cancel_all()
        for task in self._pending_delays.values():
            task.cancel()
        await self._engine.disconnect()
        self.log.info("Reactor stopped")


# ── duration parser ─────────────────────────────────────────────────────────


def _parse_duration_seconds(expr: str) -> float:
    """Parse '30s', '5m', '2h', '500ms' into seconds."""
    expr = expr.strip().lower()
    if expr.endswith("ms"):
        return float(expr[:-2]) / 1000
    if expr.endswith("s"):
        return float(expr[:-1])
    if expr.endswith("m"):
        return float(expr[:-1]) * 60
    if expr.endswith("h"):
        return float(expr[:-1]) * 3600
    raise ValueError(f"Cannot parse duration: {expr!r}")
