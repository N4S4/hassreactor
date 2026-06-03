"""
Lightweight cron-like scheduler for recurring tasks.

Supports human-readable intervals:
    @app.schedule("every 30m")
    @app.schedule("every 2h")
    @app.schedule("every 1h 30m")
    @app.schedule("0 9 * * *")        # cron expression
    @app.schedule("*/5 * * * *")      # every 5 minutes via cron
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Callable, Awaitable

logger = logging.getLogger("hassreactor.scheduler")

# Pre-compiled patterns for human-readable intervals
_RE_EVERY = re.compile(
    r"every\s+(\d+)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes|s|sec|secs|second|seconds)",
    re.IGNORECASE,
)

# 5-field cron pattern
_RE_CRON = re.compile(
    r"^(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)"
    r"\s+(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)$"
)


def _parse_interval(expression: str) -> float:
    """Parse human-readable interval into seconds.

    Returns 0 if it looks like a cron expression.
    """
    total_seconds = 0
    for match in _RE_EVERY.finditer(expression):
        value = int(match.group(1))
        unit = match.group(2).lower()[0]
        if unit == "h":
            total_seconds += value * 3600
        elif unit == "m":
            total_seconds += value * 60
        elif unit == "s":
            total_seconds += value
    return total_seconds


def _cron_matches(cron_expr: str, now: None = None) -> bool:
    """Check if a 5-field cron expression matches the current time."""
    if now is None:
        now = time.localtime()

    m = _RE_CRON.match(cron_expr.strip())
    if not m:
        return False

    fields = [m.group(i) for i in range(1, 6)]

    now_fields = [
        str(now.tm_min),   # minute 0-59
        str(now.tm_hour),  # hour 0-23
        str(now.tm_mday),  # day 1-31
        str(now.tm_mon),   # month 1-12
        str(now.tm_wday),  # weekday 0-6 (Sun=0)
    ]

    for field_expr, now_val in zip(fields, now_fields):
        if not _cron_field_matches(field_expr, now_val):
            return False
    return True


def _cron_field_matches(expr: str, value: str) -> bool:
    if expr == "*":
        return True
    for part in expr.split(","):
        if "/" in part:
            base, step = part.split("/")
            step = int(step)
            base = 0 if base == "*" else int(base)
            if (int(value) - base) % step == 0 and int(value) >= base:
                return True
        elif "-" in part:
            lo, hi = part.split("-")
            if int(lo) <= int(value) <= int(hi):
                return True
        elif part == value:
            return True
    return False


class Scheduler:
    """Manages scheduled tasks."""

    def __init__(self):
        self._tasks: list[asyncio.Task] = []

    def add(
        self,
        expression: str,
        callback: Callable[[], Awaitable[None]],
    ) -> None:
        """Schedule a recurring task.

        Args:
            expression: "every 30m" or "0 9 * * *"
            callback: async function to call
        """
        interval = _parse_interval(expression)
        is_cron = _RE_CRON.match(expression.strip())

        if interval > 0:
            task = asyncio.create_task(_run_interval(callback, interval))
        elif is_cron:
            task = asyncio.create_task(_run_cron(callback, expression.strip()))
        else:
            raise ValueError(f"Cannot parse schedule: {expression!r}")

        self._tasks.append(task)

    def cancel_all(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()


async def _run_interval(
    callback: Callable[[], Awaitable[None]], interval: float,
) -> None:
    """Run callback every `interval` seconds."""
    # Run once immediately
    try:
        await callback()
    except Exception:
        logger.exception("Error in scheduled task")
    while True:
        await asyncio.sleep(interval)
        try:
            await callback()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error in scheduled task")


async def _run_cron(
    callback: Callable[[], Awaitable[None]], cron_expr: str,
) -> None:
    """Run callback when cron expression matches (check every 30s)."""
    while True:
        now = time.localtime()
        if _cron_matches(cron_expr, now):
            try:
                await callback()
            except Exception:
                logger.exception("Error in scheduled task")
            # Sleep past this minute to avoid double-firing
            await asyncio.sleep(60 - now.tm_sec)
            continue
        # Re-check in 30s
        await asyncio.sleep(30)
