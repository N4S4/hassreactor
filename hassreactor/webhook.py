"""
Webhook server and health check endpoint for hassreactor.

Provides:
- @app.webhook("/path") — receive HTTP POSTs as triggers
- /health — Docker health check endpoint
- /metrics — Prometheus-style metrics (basic)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import EventEngine

logger = logging.getLogger("hassreactor.webhook")

_HEALTH_START_TIME = time.time()


class WebhookServer:
    """Lightweight HTTP server for webhooks and health checks.

    Usage::

        @app.webhook("/github")
        async def on_push(event):
            app.log.info("GitHub push: %s", event)

        # Health check at http://host:8080/health
    """

    def __init__(
        self,
        engine: "EventEngine",
        port: int = 8080,
        bind: str = "0.0.0.0",
    ):
        import os
        self._engine = engine
        self._port = int(os.getenv("WEBHOOK_PORT", str(port)))
        self._bind = os.getenv("WEBHOOK_BIND", bind)
        self._routes: dict[str, Callable[[dict], Awaitable[None]]] = {}
        self._server = None
        self._running = False

    def on(self, path: str) -> Callable:
        """Register a webhook handler.

        Usage::

            @app.webhook.on("/github")
            async def handler(data): ...
        """

        def decorator(fn: Callable):
            self._routes[path] = fn
            return fn

        return decorator

    async def start(self) -> None:
        """Start the HTTP server (non-blocking, uses asyncio)."""
        if self._running:
            return
        self._running = True
        asyncio.create_task(self._run_server())

    async def stop(self) -> None:
        self._running = False
        if self._server:
            await self._server.cleanup()

    async def _run_server(self) -> None:
        import aiohttp
        from aiohttp import web

        async def handle_health(request: web.Request) -> web.Response:
            uptime = time.time() - _HEALTH_START_TIME
            return web.json_response({
                "status": "ok",
                "uptime_seconds": round(uptime, 1),
                "ha_connected": self._engine.connected,
            })

        async def handle_webhook(request: web.Request) -> web.Response:
            path = "/" + request.match_info.get("path", "")
            handler = self._routes.get(path)
            if not handler:
                return web.json_response(
                    {"error": "not found"}, status=404
                )
            try:
                body = await request.json()
            except Exception:
                body = {"raw": await request.text()}
            try:
                await handler(body)
            except Exception:
                logger.exception("Error in webhook handler for %s", path)
            return web.json_response({"ok": True})

        async def handle_metrics(request: web.Request) -> web.Response:
            return web.Response(
                text=f"hassreactor_uptime_seconds {time.time() - _HEALTH_START_TIME:.0f}\n"
                     f"hassreactor_ha_connected {1 if self._engine.connected else 0}\n",
                content_type="text/plain",
            )

        app = web.Application()
        app.router.add_get("/health", handle_health)
        app.router.add_get("/metrics", handle_metrics)
        app.router.add_post("/webhook/{path:.*}", handle_webhook)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self._bind, self._port)
        await site.start()
        logger.info("Webhook server listening on %s:%d", self._bind, self._port)

        self._server = runner

        # Keep alive
        while self._running:
            await asyncio.sleep(10)

        await runner.cleanup()
