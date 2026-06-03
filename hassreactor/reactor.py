"""
Reactor — the main entry point for hassreactor.

Ties together the WebSocket engine, service proxy, scheduler,
sun calculator, Telegram sender, webhook server, and hot-reloader
into a single interface for Home Assistant automations in Python.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import os
import signal
import sys
import time
from typing import Any, Callable, Awaitable

from .domain_proxy import DomainProxy
from .engine import EventEngine
from .scheduler import Scheduler


class TriggerEvent:
    """Event passed to callbacks."""

    def __init__(self, event_data: dict, engine: EventEngine | None = None):
        self._engine = engine
        data = event_data.get("data", event_data)
        self.entity_id: str = data.get("entity_id", "")
        self.old_state: dict | None = data.get("old_state")
        self.new_state: dict | None = data.get("new_state")
        self.event_type: str = event_data.get("event_type", "")
        self.origin: str = event_data.get("origin", "")
        self.time_fired: str = event_data.get("time_fired", "")
        ns = self.new_state or {}
        self.state: str = ns.get("state", "")
        self.attributes: dict = ns.get("attributes", {})

    def __repr__(self) -> str:
        return (
            f"TriggerEvent(entity_id={self.entity_id!r}, "
            f"state={self.state!r}, event_type={self.event_type!r})"
        )


# ── Chainable trigger builder ───────────────────────────────────────────────


class _TriggerBuilder:
    """Returned by @app.when() — supports .and_() and .unless() chaining."""

    def __init__(
        self,
        reactor: "Reactor",
        entity_id: str,
        conditions: dict,
        fn: Callable | None = None,
    ):
        self._reactor = reactor
        self._entity_id = entity_id
        self._conditions = conditions
        self._fn = fn
        self._chain: list[tuple[str, dict]] = []  # (entity_id, conditions)

    def __call__(self, fn: Callable) -> Callable:
        """Make _TriggerBuilder usable as a decorator."""
        self._fn = fn
        self._reactor._register_trigger(
            self._entity_id, self._conditions, self._chain, fn
        )
        return fn

    def and_(self, entity_id: str, **kw) -> "_TriggerBuilder":
        """Add another condition that must also be true."""
        conds = {}
        for k, v in kw.items():
            if k in ("within", "throttle"):
                conds[k] = v
            else:
                conds[k] = v
        self._chain.append((entity_id, conds))
        return self

    def unless(self, entity_id: str, **kw) -> "_TriggerBuilder":
        """Add a condition that must NOT be true (negated)."""
        conds = dict(kw)
        conds["_negate"] = True
        self._chain.append((entity_id, conds))
        return self

    def then(self, fn: Callable) -> "_TriggerBuilder":
        """Set the callback for a pre-built trigger."""
        self._fn = fn
        self._reactor._register_trigger(
            self._entity_id, self._conditions, self._chain, fn
        )
        return self


# ── Sun callback wrapper ─────────────────────────────────────────────────────


class _SunTrigger:
    """Returned by @app.sun() — holds schedule registration."""

    def __init__(self, reactor: "Reactor", fn: Callable, task: asyncio.Task | None):
        self._reactor = reactor
        self._fn = fn
        self._task = task


# ── Reactor ─────────────────────────────────────────────────────────────────


class Reactor:
    """Main application class for hassreactor.

    Usage::

        app = Reactor()          # reads HA_URL, HA_TOKEN from env

        @app.when("sensor.temp", above=28)
        async def hot(event):
            await app.fan.turn_on(entity_id="fan.ventilatore")

        @app.when("sensor.motion", to="on").unless("input_boolean.vacation", to="on")
        async def motion(event):
            await app.light.turn_on(entity_id="light.hall")

        @app.template("{{ states('sensor.a') | float > states('sensor.b') | float }}")
        async def template_trigger(event):
            app.log.info("A > B!")

        @app.sun(after="sunset", offset="-30m")
        async def lights_on():
            await app.light.turn_on(entity_id="light.porch")

        if __name__ == "__main__":
            app.run()
    """

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        verify_ssl: bool = True,
        auto_reconnect: bool = True,
        hot_reload: str | None = None,  # path to watch
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
        self._running = False
        self._hot_reload_path = hot_reload
        self._hot_reload_mtime: float = 0

        # Entity triggers: (entity_id, conditions, chain_list, fn)
        self._triggers: list[tuple[str, dict, list[tuple[str, dict]], Callable]] = []
        # Template triggers: (template_str, entity_ids, fn, last_value)
        self._template_triggers: list[tuple[str, list[str], Callable, bool]] = []
        # Keyword to parse for templates
        self._template_kw = {}

        self._engine.on_reconnect(self._on_reconnect)

        self.log = logging.getLogger("hassreactor")
        self.store: dict[str, Any] = {}

        # State for within / throttle
        self._last_fired: dict[str, float] = {}
        self._pending_delays: dict[str, asyncio.Task] = {}

        # Lazy imports
        self._sun_calc = None
        self._telegram_bot = None
        self._webhook_server = None

    # -- domain access ---------------------------------------------------------

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._proxy, name)

    # -- sun access ------------------------------------------------------------

    @property
    def solar(self):
        """Access sun calculator for sunrise/sunset queries.

        Usage: t = await app.solar.sunrise()
        """
        if self._sun_calc is None:
            from .sun import SunCalc
            self._sun_calc = SunCalc(self._engine)
        return self._sun_calc

    # -- telegram --------------------------------------------------------------

    @property
    def telegram(self):
        """Send Telegram messages natively."""
        if self._telegram_bot is None:
            from .telegram import TelegramBot
            self._telegram_bot = TelegramBot(self._engine)
        return self._telegram_bot

    # -- webhook ---------------------------------------------------------------

    @property
    def webhook(self):
        """Access webhook server."""
        if self._webhook_server is None:
            from .webhook import WebhookServer
            self._webhook_server = WebhookServer(self._engine)
        return self._webhook_server

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
        rose_by: float | None = None,
        fell_by: float | None = None,
        in_: str | None = None,
    ) -> _TriggerBuilder:
        """Decorator: trigger on state changes. Returns chainable builder.

        Args:
            entity_id: HA entity to watch
            above: cross ABOVE numeric threshold
            below: cross BELOW numeric threshold
            to: state changes TO exact value
            changes: fire on ANY change
            within: debounce (e.g. "2s", "500ms")
            throttle: rate limit (e.g. "10s")
            for_: state must persist N seconds
            rose_by: fire when value rises by N over `in_` window
            fell_by: fire when value falls by N over `in_` window
            in_: time window for rose_by/fell_by (e.g. "10m")

        Chain with .and_() / .unless() / .then():
            @app.when("sensor.temp", above=28).and_("sensor.humidity", above=70)
        """
        conditions = self._build_conditions(**{
            k: v for k, v in {
                "above": above, "below": below, "to": to,
                "changes": changes, "within": within, "throttle": throttle,
                "for_": for_, "rose_by": rose_by, "fell_by": fell_by,
                "in_": in_,
            }.items() if v is not None
        })
        return _TriggerBuilder(self, entity_id, conditions)

    def on(self, event_type: str):
        """Decorator: react to any Home Assistant event."""

        def decorator(fn: Callable):
            self._engine.on_event(event_type, fn)
            return fn

        return decorator

    def schedule(self, expression: str):
        """Decorator: run on a schedule."""

        def decorator(fn: Callable):
            self._scheduler.add(expression, fn)
            return fn

        return decorator

    def template(self, template_str: str):
        """Decorator: trigger on a template expression.

        Example::

            @app.template("{{ states('sensor.a') | float > states('sensor.b') | float }}")
            async def when_a_gt_b(event):
                ...
        """
        entity_ids = _parse_template_entities(template_str)

        def decorator(fn: Callable):
            self._template_triggers.append((template_str, entity_ids, fn, False))
            return fn

        return decorator

    def sun(
        self,
        *,
        before: str = "",
        after: str = "",
        offset: str = "0m",
    ):
        """Decorator: trigger at sunrise/sunset.

        Args:
            before: "sunrise" or "sunset" — fire before
            after: "sunrise" or "sunset" — fire after
            offset: offset like "-30m" or "1h" from the event

        Example::

            @app.sun(after="sunset", offset="-30m")
            async def lights_on():
                await app.light.turn_on(entity_id="light.porch")
        """

        def decorator(fn: Callable):
            event = before or after
            direction = "before" if before else "after"
            offset_s = _parse_duration_seconds(offset)
            # Defer registration until sun module is imported
            self._scheduler.add_sun(
                event, direction, offset_s, fn, self._engine
            )
            return fn

        return decorator

    # -- state access ----------------------------------------------------------

    async def get_state(self, entity_id: str) -> str | None:
        s = await self._engine.get_state(entity_id)
        if s:
            return s.get("state")
        return None

    async def get_states(self) -> list[dict]:
        return await self._engine.get_states()

    # -- lifecycle ------------------------------------------------------------

    def run(self) -> None:
        """Start the reactor (blocking, with optional hot-reload)."""
        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            self.log.info("Shutting down...")

    async def start(self) -> None:
        await self._connect()

    async def stop(self) -> None:
        await self._shutdown()

    # -- internal -------------------------------------------------------------

    def _register_trigger(
        self,
        entity_id: str,
        conditions: dict,
        chain: list[tuple[str, dict]],
        fn: Callable,
    ) -> None:
        """Register a trigger with its chain of and_/unless conditions."""
        self._triggers.append((entity_id, conditions, chain, fn))

    def _build_conditions(self, **kw) -> dict:
        conds = {}
        for k, v in kw.items():
            if k in ("within", "throttle", "for_", "in_"):
                conds[k] = _parse_duration_seconds(v) if isinstance(v, str) else v
            else:
                conds[k] = v
        return conds

    async def _run(self) -> None:
        await self._connect()

        # Start scheduler — now safe because the event loop is running
        self._scheduler.start()

        # Start hot-reload watcher
        if self._hot_reload_path:
            self._hot_reload_mtime = os.path.getmtime(self._hot_reload_path)
            asyncio.create_task(self._hot_reload_watcher())

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

    async def _hot_reload_watcher(self) -> None:
        """Poll the automations file for changes and hot-reload."""
        path = self._hot_reload_path
        while self._running:
            await asyncio.sleep(1)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime == self._hot_reload_mtime:
                continue
            self._hot_reload_mtime = mtime
            self.log.info("File changed — hot-reloading %s", path)
            await self._hot_reload(path)

    async def _hot_reload(self, path: str) -> None:
        """Reload the automations module and re-register triggers."""
        # Cancel all pending delays
        for task in self._pending_delays.values():
            task.cancel()
        self._pending_delays.clear()

        # Cancel old scheduler tasks
        self._scheduler.cancel_all()

        # Clear engine listeners
        self._engine._listeners.clear()
        self._engine._generic_listeners.clear()

        # Reset internal state
        self._triggers.clear()
        self._template_triggers.clear()

        # Re-import the module
        module_name = os.path.splitext(os.path.basename(path))[0]
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                self.log.exception("Hot-reload failed — keeping old state")
                return

        # Re-register triggers from the reloaded module
        # (The decorators already re-populated self._triggers etc.)
        for entity_id, conditions, chain, fn in self._triggers:
            # Register primary entity listener
            self._engine.on_state_change(
                entity_id,
                self._make_listener(entity_id, conditions, chain, fn),
            )
            # Register chain entity listeners
            for ch_eid, ch_conds in chain:
                self._engine.on_state_change(ch_eid, lambda d: None)  # placeholder — chain is evaluated in primary

        # Re-register template triggers
        for tmpl_str, entity_ids, fn, _ in self._template_triggers:
            for eid in entity_ids:
                self._engine.on_state_change(
                    eid,
                    self._make_template_listener(tmpl_str, entity_ids, fn),
                )

        self.log.info(
            "Hot-reload complete — %d triggers, %d templates",
            len(self._triggers), len(self._template_triggers),
        )

        # Restart scheduler with new tasks
        self._scheduler.start()

    async def _on_reconnect(self) -> None:
        """Re-register listeners after auto-reconnect."""
        for entity_id, conditions, chain, fn in self._triggers:
            self._engine.on_state_change(
                entity_id,
                self._make_listener(entity_id, conditions, chain, fn),
            )
        for tmpl_str, entity_ids, fn, _ in self._template_triggers:
            for eid in entity_ids:
                self._engine.on_state_change(
                    eid,
                    self._make_template_listener(tmpl_str, entity_ids, fn),
                )
        self.log.debug("Re-registered %d triggers after reconnect", len(self._triggers))

    async def _connect(self) -> None:
        await self._engine.connect()

        # Register entity triggers
        for entity_id, conditions, chain, fn in self._triggers:
            self._engine.on_state_change(
                entity_id,
                self._make_listener(entity_id, conditions, chain, fn),
            )

        # Register template triggers
        for tmpl_str, entity_ids, fn, last_val in self._template_triggers:
            for eid in entity_ids:
                self._engine.on_state_change(
                    eid,
                    self._make_template_listener(tmpl_str, entity_ids, fn),
                )

        self._running = True
        self.log.info(
            "Reactor running — %d triggers, %d templates, %d schedules",
            len(self._triggers),
            len(self._template_triggers),
            len(self._scheduler._tasks),
        )

    # -- listener factory -----------------------------------------------------

    def _make_listener(
        self, entity_id: str, conditions: dict,
        chain: list[tuple[str, dict]], fn: Callable,
    ):
        within_s = conditions.get("within")
        throttle_s = conditions.get("throttle")
        for_s = conditions.get("for_")
        rose_by = conditions.get("rose_by")
        fell_by = conditions.get("fell_by")
        in_s = conditions.get("in_")

        async def listener(data: dict):
            event = TriggerEvent(data)

            if not conditions and not chain:
                return

            # Record trend data
            new_state = data.get("new_state")
            if new_state:
                self._engine.record_state(entity_id, new_state.get("state", ""))

            # Check trend conditions (rose_by / fell_by)
            if rose_by is not None and in_s is not None:
                change = self._engine.get_trend_change(entity_id, in_s)
                if change is None or change < rose_by:
                    return

            if fell_by is not None and in_s is not None:
                change = self._engine.get_trend_change(entity_id, in_s)
                if change is None or change > -fell_by:
                    return

            # Check chain conditions (and_ / unless)
            if chain and not await self._check_chain(chain):
                return

            # "for_" duration handling
            if for_s is not None:
                new_state = data.get("new_state")
                if not new_state:
                    return
                if not self._condition_matches(conditions, data):
                    task = self._pending_delays.pop(entity_id, None)
                    if task:
                        task.cancel()
                    return
                if entity_id in self._pending_delays:
                    return
                self._pending_delays[entity_id] = asyncio.create_task(
                    self._fire_after_delay(entity_id, fn, event, for_s)
                )
                return
            else:
                for key in list(self._pending_delays):
                    if key == entity_id:
                        task = self._pending_delays.pop(key, None)
                        if task:
                            task.cancel()

            if not self._condition_matches(conditions, data):
                return

            # "within" debounce
            if within_s is not None:
                key = f"within:{entity_id}"
                if key in self._pending_delays:
                    self._pending_delays[key].cancel()
                self._pending_delays[key] = asyncio.create_task(
                    self._fire_after_delay(key, fn, event, within_s)
                )
                return

            # "throttle" rate limit
            if throttle_s is not None:
                key = f"throttle:{entity_id}"
                now = time.monotonic()
                last = self._last_fired.get(key, 0)
                if now - last < throttle_s:
                    return
                self._last_fired[key] = now

            await fn(event)

        return listener

    def _make_template_listener(
        self, template_str: str, entity_ids: list[str], fn: Callable,
    ):
        """Build a listener that evaluates a template and fires on change."""

        async def listener(data: dict):
            event = TriggerEvent(data)
            try:
                result = await self._eval_template(template_str)
            except Exception:
                return

            # Find the index of this template trigger
            for idx, (ts, eids, f, last_val) in enumerate(self._template_triggers):
                if ts == template_str:
                    if bool(result) != last_val and bool(result):
                        self._template_triggers[idx] = (ts, eids, f, bool(result))
                        await fn(event)
                    else:
                        self._template_triggers[idx] = (ts, eids, f, bool(result))
                    break

        return listener

    async def _eval_template(self, template_str: str) -> bool:
        """Evaluate a template expression like '{{ states('sensor.a') | float > 1 }}'."""
        import re

        # Extract the inner expression
        m = re.search(r"\{\{\s*(.+?)\s*\}\}", template_str, re.DOTALL)
        if not m:
            return False
        expr = m.group(1)

        # Resolve states('entity_id')
        def _replace_state(match):
            eid = match.group(1).strip("'\"")
            return f"float({_get_state_value(eid)!r})"

        expr = re.sub(r"states\(\s*['\"]([^'\"]+)['\"]\s*\)", _replace_state, expr)

        # Resolve float filters (already in float() wrapper, strip | float)
        expr = re.sub(r"\|\s*float", "", expr)

        # Simple evaluation
        try:
            return bool(eval(expr, {"__builtins__": {}}, {}))
        except Exception:
            return False

        async def _get_state_value(eid):
            s = await self._engine.get_state(eid)
            return s.get("state", "0") if s else "0"

    async def _check_chain(self, chain: list[tuple[str, dict]]) -> bool:
        """Check and_/unless conditions against current HA states."""
        for entity_id, conds in chain:
            state = await self._engine.get_state(entity_id)
            if not state:
                return False
            negate = conds.pop("_negate", False)
            matches = self._simple_condition_match(conds, state)
            if negate:
                if matches:
                    return False
            else:
                if not matches:
                    return False
        return True

    def _simple_condition_match(self, conditions: dict, state: dict) -> bool:
        """Check conditions against a state dict (for chain evaluation)."""
        state_val = state.get("state", "")
        if "to" in conditions:
            return state_val == conditions["to"]
        if "above" in conditions:
            try:
                return float(state_val) > conditions["above"]
            except (TypeError, ValueError):
                return False
        if "below" in conditions:
            try:
                return float(state_val) < conditions["below"]
            except (TypeError, ValueError):
                return False
        return True

    def _condition_matches(self, conditions: dict, data: dict) -> bool:
        """Check if event data matches trigger conditions."""
        if not conditions:
            return False
        if conditions.get("changes"):
            return True

        new_state = data.get("new_state")
        if not new_state:
            return False

        state_val = new_state.get("state", "")

        if "to" in conditions:
            return state_val == conditions["to"]

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

    async def _fire_after_delay(
        self, key: str, fn: Callable, event: TriggerEvent, delay: float,
    ) -> None:
        try:
            await asyncio.sleep(delay)
            await fn(event)
        except asyncio.CancelledError:
            pass
        finally:
            self._pending_delays.pop(key, None)

    async def _shutdown(self) -> None:
        self._running = False
        self._scheduler.cancel_all()
        for task in self._pending_delays.values():
            task.cancel()
        await self._engine.disconnect()
        self.log.info("Reactor stopped")


# ── Helpers ─────────────────────────────────────────────────────────────────


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


def _parse_template_entities(template_str: str) -> list[str]:
    """Extract entity IDs from a template string."""
    import re
    return re.findall(r"states\(\s*['\"]([^'\"]+)['\"]\s*\)", template_str)
