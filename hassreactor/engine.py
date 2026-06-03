"""
WebSocket event engine for Home Assistant.

Handles authentication, subscription to events, auto-reconnect
with exponential backoff, and dispatches to registered triggers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Awaitable

import aiohttp

logger = logging.getLogger("hassreactor.engine")

_RECONNECT_MIN = 1.0
_RECONNECT_MAX = 60.0


class EventEngine:
    """Low-level WebSocket client for Home Assistant with auto-reconnect."""

    def __init__(
        self, url: str, token: str,
        verify_ssl: bool = True,
        auto_reconnect: bool = True,
    ):
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        url = url.rstrip("/")
        self._http_url = url
        self._ws_url = url.replace("http://", "ws://").replace("https://", "wss://")
        self._ws_url = f"{self._ws_url}/api/websocket"
        self._token = token
        self._verify_ssl = verify_ssl
        self._auto_reconnect = auto_reconnect
        self._msg_id = 0
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        # Entity-level listeners  (state_changed)
        self._listeners: dict[str, list[Callable[[dict], Awaitable[None]]]] = {}
        # Generic event listeners  (any event_type)
        self._generic_listeners: dict[str, list[Callable[[dict], Awaitable[None]]]] = {}
        self._result_futures: dict[int, asyncio.Future] = {}
        self._running = False
        self._connected = False
        self._reconnect_delay = _RECONNECT_MIN
        self._on_reconnect: list[Callable[[], Awaitable[None]]] = []
        # Trend history: entity_id → list of (timestamp, value)
        self._trend_history: dict[str, list[tuple[float, float]]] = {}
        self._trend_maxlen = 300  # keep last N samples per entity

    # -- public API -----------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Connect and start the main loop (with auto-reconnect if enabled)."""
        self._running = True
        await self._connect_once()

        # Launch keep-alive loop for auto-reconnect
        asyncio.create_task(self._keep_alive_loop())

    async def disconnect(self) -> None:
        """Close the WebSocket connection and stop reconnecting."""
        self._running = False
        self._connected = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session:
            await self._session.close()
        logger.info("Disconnected from Home Assistant")

    async def call_service(
        self, domain: str, service: str, data: dict | None = None,
        target: dict | None = None,
    ) -> dict:
        """Call a Home Assistant service via REST API."""
        url = f"{self._http_url}/api/services/{domain}/{service}"
        body: dict[str, Any] = {}
        if data:
            body = dict(data)
        if target:
            body["target"] = target
        async with self._session.post(
            url, json=body,
            headers={"Authorization": f"Bearer {self._token}"},
            verify_ssl=self._verify_ssl,
        ) as resp:
            return await resp.json()

    async def get_states(self) -> list[dict]:
        """Get all entity states via REST API."""
        url = f"{self._http_url}/api/states"
        async with self._session.get(
            url,
            headers={"Authorization": f"Bearer {self._token}"},
            verify_ssl=self._verify_ssl,
        ) as resp:
            return await resp.json()

    async def get_state(self, entity_id: str) -> dict | None:
        """Get single entity state."""
        url = f"{self._http_url}/api/states/{entity_id}"
        async with self._session.get(
            url,
            headers={"Authorization": f"Bearer {self._token}"},
            verify_ssl=self._verify_ssl,
        ) as resp:
            if resp.status == 404:
                return None
            return await resp.json()

    def on_state_change(
        self, entity_id: str, callback: Callable[[dict], Awaitable[None]],
    ) -> None:
        """Register a callback for state_changed events on a specific entity."""
        if entity_id not in self._listeners:
            self._listeners[entity_id] = []
        self._listeners[entity_id].append(callback)

    def on_event(
        self, event_type: str, callback: Callable[[dict], Awaitable[None]],
    ) -> None:
        """Register a callback for any HA event type (not just state_changed)."""
        if event_type not in self._generic_listeners:
            self._generic_listeners[event_type] = []
        self._generic_listeners[event_type].append(callback)

    def on_reconnect(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Register a callback to run after every successful reconnection."""
        self._on_reconnect.append(callback)

    def record_state(self, entity_id: str, state_val: str) -> None:
        """Record a state sample for trend tracking."""
        try:
            val = float(state_val)
        except (TypeError, ValueError):
            return
        now = time.monotonic()
        if entity_id not in self._trend_history:
            self._trend_history[entity_id] = []
        hist = self._trend_history[entity_id]
        hist.append((now, val))
        if len(hist) > self._trend_maxlen:
            hist.pop(0)

    def get_trend_change(
        self, entity_id: str, window_s: float
    ) -> float | None:
        """Return value change over the last `window_s` seconds, or None."""
        hist = self._trend_history.get(entity_id)
        if not hist or len(hist) < 2:
            return None
        now = time.monotonic()
        cutoff = now - window_s
        first = None
        latest = hist[-1][1]
        for ts, val in hist:
            if ts >= cutoff:
                if first is None:
                    first = val
                break
            first = val
        if first is None:
            first = hist[0][1]
        return latest - first

    # -- internal -------------------------------------------------------------

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def _keep_alive_loop(self) -> None:
        """Monitor connection health and reconnect when needed."""
        while self._running:
            await asyncio.sleep(2)
            if not self._connected and self._auto_reconnect:
                logger.info("Reconnecting in %.1fs...", self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                if not self._running:
                    break
                try:
                    await self._connect_once()
                    self._reconnect_delay = _RECONNECT_MIN
                except Exception:
                    self._reconnect_delay = min(
                        self._reconnect_delay * 2, _RECONNECT_MAX
                    )
                    logger.warning(
                        "Reconnect failed, next in %.1fs", self._reconnect_delay
                    )

    async def _connect_once(self) -> None:
        """Single-shot: authenticate, subscribe, launch listener."""
        # Close stale session
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session:
            await self._session.close()

        self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(
            self._ws_url, verify_ssl=self._verify_ssl, heartbeat=30,
        )

        # Read auth required
        auth_msg = await self._ws.receive_json()
        if auth_msg.get("type") != "auth_required":
            raise RuntimeError(f"Unexpected message: {auth_msg}")

        # Authenticate
        await self._ws.send_json({
            "type": "auth",
            "access_token": self._token,
        })
        auth_result = await self._ws.receive_json()
        if auth_result.get("type") != "auth_ok":
            raise RuntimeError(f"Auth failed: {auth_result}")

        # Subscribe to state_changed
        sub_id = self._next_id()
        await self._ws.send_json({
            "id": sub_id,
            "type": "subscribe_events",
            "event_type": "state_changed",
        })
        sub_result = await self._ws.receive_json()
        if not sub_result.get("success"):
            raise RuntimeError(f"state_changed subscribe failed: {sub_result}")

        # Subscribe to all generic event types
        for event_type in self._generic_listeners:
            sub_id = self._next_id()
            await self._ws.send_json({
                "id": sub_id,
                "type": "subscribe_events",
                "event_type": event_type,
            })
            sub_result = await self._ws.receive_json()
            if not sub_result.get("success"):
                logger.warning(
                    "Failed to subscribe to %s: %s", event_type, sub_result
                )

        self._connected = True
        logger.info("Connected to Home Assistant WebSocket (%d entity listeners, %d event types)",
                     sum(len(v) for v in self._listeners.values()),
                     len(self._generic_listeners))
        asyncio.create_task(self._listen_loop())

        # Fire reconnect callbacks
        for cb in self._on_reconnect:
            try:
                await cb()
            except Exception:
                logger.exception("Error in reconnect callback")

    async def _listen_loop(self) -> None:
        """Long-running loop: read WebSocket messages and dispatch."""
        while self._running and self._connected:
            try:
                ws_msg = await asyncio.wait_for(self._ws.receive(), timeout=30)
            except asyncio.TimeoutError:
                continue
            except Exception:
                logger.warning("WebSocket disconnected")
                break

            # Handle binary frames (pings) and PONG
            if ws_msg.type == aiohttp.WSMsgType.CLOSE:
                logger.info("WebSocket close frame received")
                break
            if ws_msg.type == aiohttp.WSMsgType.CLOSED:
                break
            if ws_msg.type == aiohttp.WSMsgType.ERROR:
                logger.error("WebSocket error frame")
                break
            if ws_msg.type == aiohttp.WSMsgType.PING:
                await self._ws.pong()
                continue
            if ws_msg.type == aiohttp.WSMsgType.PONG:
                continue
            if ws_msg.type != aiohttp.WSMsgType.TEXT:
                continue

            try:
                msg = json.loads(ws_msg.data)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid JSON in WebSocket message")
                continue

            msg_type = msg.get("type")
            if msg_type == "event":
                event = msg.get("event", {})
                event_type = event.get("event_type", "")

                # Dispatch to generic listeners
                generic_cbs = self._generic_listeners.get(event_type, [])
                for cb in generic_cbs:
                    try:
                        await cb(event)
                    except Exception:
                        logger.exception("Error in %s listener", event_type)

                # Dispatch to entity listeners (state_changed only)
                if event_type == "state_changed":
                    data = event.get("data", {})
                    entity_id = data.get("entity_id", "")
                    callbacks = self._listeners.get(entity_id, [])
                    for cb in callbacks:
                        try:
                            await cb(data)
                        except Exception:
                            logger.exception(
                                "Error in listener for %s", entity_id
                            )
            elif msg_type == "result":
                msg_id = msg.get("id")
                future = self._result_futures.pop(msg_id, None)
                if future:
                    future.set_result(msg)

        self._connected = False
