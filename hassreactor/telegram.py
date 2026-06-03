"""
Native Telegram sender for hassreactor.

Send messages directly via Telegram Bot API
without going through Home Assistant's notify.telegram.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import EventEngine

logger = logging.getLogger("hassreactor.telegram")


class TelegramBot:
    """Send Telegram messages directly from automations.

    Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars,
    or pass them explicitly.

    Usage::

        await app.telegram.send("Door opened!")
        await app.telegram.send("Temp alert: 32°C", parse_mode="HTML")
    """

    def __init__(
        self,
        engine: "EventEngine",
        token: str = "",
        chat_id: str = "",
    ):
        import os
        self._token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self._engine = engine

    async def send(
        self,
        text: str,
        parse_mode: str = "",
        chat_id: str = "",
        disable_notification: bool = False,
    ) -> dict:
        """Send a text message via Telegram Bot API.

        Args:
            text: Message text
            parse_mode: "HTML" or "MarkdownV2" (optional)
            chat_id: Override default chat ID
            disable_notification: Send silently
        """
        if not self._token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN not set. "
                "Set the env var or pass it to TelegramBot(token=...)."
            )
        cid = chat_id or self._chat_id
        if not cid:
            raise ValueError(
                "No chat_id. Set TELEGRAM_CHAT_ID env var or pass it explicitly."
            )

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        body = {
            "chat_id": cid,
            "text": text,
            "disable_notification": disable_notification,
        }
        if parse_mode:
            body["parse_mode"] = parse_mode

        ssl = self._engine._verify_ssl
        async with self._engine._session.post(url, json=body, verify_ssl=ssl) as resp:
            return await resp.json()
