"""
Sun calculator for hassreactor.

Provides @app.sun() triggers and sun position queries.
Uses a simple algorithm — no external dependencies.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time as _time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import EventEngine

logger = logging.getLogger("hassreactor.sun")


# ── Sun position algorithm (NOAA simplified) ────────────────────────────────


def _sun_events(lat: float, lon: float, date: datetime | None = None) -> dict:
    """Calculate sunrise/sunset times for a given date and location.

    Returns dict with 'sunrise' and 'sunset' as Unix timestamps.
    Algorithm from NOAA Solar Calculator, simplified.
    """
    if date is None:
        date = datetime.now(timezone.utc)
    # Day of year
    doy = date.timetuple().tm_yday
    # Approximate solar noon
    lng_hour = lon / 15.0
    t = doy + ((12 - lng_hour) / 24)
    # Solar mean anomaly
    m = (0.9856 * t) - 3.289
    # Sun's true longitude
    l = m + (1.916 * math.sin(math.radians(m))) + (0.020 * math.sin(math.radians(2 * m))) + 282.634
    l = l % 360
    # Sun's right ascension
    ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l))))
    ra = ra % 360
    l_quad = (math.floor(l / 90)) * 90
    ra_quad = (math.floor(ra / 90)) * 90
    ra = ra + (l_quad - ra_quad)
    ra = ra / 15
    # Sun's declination
    sin_dec = 0.39782 * math.sin(math.radians(l))
    cos_dec = math.cos(math.asin(sin_dec))
    # Sunset hour angle
    cos_h = (-math.sin(math.radians(0.8333)) - math.sin(math.radians(lat)) * sin_dec) / (
        math.cos(math.radians(lat)) * cos_dec
    )
    if cos_h > 1:
        cos_h = 1  # Polar night
    elif cos_h < -1:
        cos_h = -1  # Polar day
    h = math.degrees(math.acos(cos_h))
    # Sunrise / sunset UTC hours
    sunrise_h = 12 - h / 15 - lng_hour
    sunset_h = 12 + h / 15 - lng_hour
    # Convert to datetimes
    base = datetime(date.year, date.month, date.day, tzinfo=timezone.utc)
    sunrise = base.timestamp() + sunrise_h * 3600
    sunset = base.timestamp() + sunset_h * 3600
    # Next sunrise (if current already passed)
    next_base = datetime(date.year, date.month, date.day + 1, tzinfo=timezone.utc)
    next_sunrise = next_base.timestamp() + sunrise_h * 3600
    return {
        "sunrise": sunrise,
        "sunset": sunset,
        "next_sunrise": next_sunrise,
    }


class SunCalc:
    """Query sun position and schedule sun-based triggers."""

    def __init__(self, engine: "EventEngine"):
        self._engine = engine
        self._lat: float | None = None
        self._lon: float | None = None

    async def _ensure_location(self) -> tuple[float, float]:
        """Fetch latitude/longitude from HA config."""
        if self._lat is not None:
            return self._lat, self._lon
        # Try to get home zone
        try:
            config = await self._engine.get_state("zone.home")
            if config:
                attrs = config.get("attributes", {})
                self._lat = float(attrs.get("latitude", 0))
                self._lon = float(attrs.get("longitude", 0))
        except Exception:
            pass
        if not self._lat:
            # Fallback: try HA config via REST
            try:
                url = f"{self._engine._http_url}/api/config"
                import aiohttp
                async with self._engine._session.get(
                    url,
                    headers={"Authorization": f"Bearer {self._engine._token}"},
                    verify_ssl=self._engine._verify_ssl,
                ) as resp:
                    data = await resp.json()
                    self._lat = float(data.get("latitude", 0))
                    self._lon = float(data.get("longitude", 0))
            except Exception:
                self._lat, self._lon = 0, 0
        return self._lat, self._lon

    async def sunrise(self) -> float:
        """Return today's sunrise as Unix timestamp."""
        lat, lon = await self._ensure_location()
        return _sun_events(lat, lon)["sunrise"]

    async def sunset(self) -> float:
        """Return today's sunset as Unix timestamp."""
        lat, lon = await self._ensure_location()
        return _sun_events(lat, lon)["sunset"]

    async def next_sunrise(self) -> float:
        """Return next sunrise as Unix timestamp."""
        lat, lon = await self._ensure_location()
        return _sun_events(lat, lon)["next_sunrise"]

    async def is_day(self) -> bool:
        """Return True if sun is currently up."""
        lat, lon = await self._ensure_location()
        events = _sun_events(lat, lon)
        now = _time.time()
        return events["sunrise"] < now < events["sunset"]

    async def schedule(
        self,
        fn,
        event: str,       # "sunrise" or "sunset"
        direction: str,   # "before" or "after"
        offset_s: float,
    ) -> asyncio.Task:
        """Schedule a callback at sunrise/sunset + offset.

        Returns a Task that can be cancelled.
        """

        async def _runner():
            lat, lon = await self._ensure_location()
            while True:
                events = _sun_events(lat, lon)
                target = events.get(event, 0) + (offset_s if direction == "after" else -offset_s)
                now = _time.time()
                delay = target - now
                if delay < 0:
                    # Event already passed, wait for next day
                    delay += 86400
                await asyncio.sleep(delay)
                try:
                    await fn()
                except Exception:
                    logger.exception("Error in sun trigger")

        return asyncio.create_task(_runner())
