"""OpenSky Network ADS-B flight ingestion service — Story 1.5.

Polls https://opensky-network.org/api/states/all every 10 seconds,
normalises aircraft state vectors into GlobeEvents, and hands them to
the base class for upsert + Redis publish.

State vector index map (OpenSky docs):
    0  icao24           — unique 24-bit ICAO transponder address (hex)
    1  callsign         — aircraft call sign (may be null)
    2  origin_country
    3  time_position    — Unix timestamp of last position update
    4  last_contact     — Unix timestamp of last telemetry contact
    5  longitude        — WGS-84  (deg)
    6  latitude         — WGS-84  (deg)
    7  baro_altitude    — barometric altitude  (m)
    8  on_ground        — bool
    9  velocity         — ground speed  (m/s)
    10 true_track       — track angle clockwise from north  (deg)
    11 vertical_rate    — (m/s)
    12 sensors          — (unused)
    13 geo_altitude     — geometric altitude  (m) — preferred
    14 squawk           — Mode-C squawk code
    15 spi              — special purpose indicator
    16 position_source  — 0=ADS-B, 1=ASTERIX, 2=MLAT
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from collections import deque
from typing import Any

import httpx

from app.config import settings
from app.services.ingestion.base import BaseIngestionService

OPENSKY_URL = "https://opensky-network.org/api/states/all"

# Military callsign prefixes (US, NATO, Russian, etc.)
_MILITARY_RE = re.compile(
    r"^(RCH|REACH|JAKE|DUKE|ROCKY|SPAR|IRON|VENUS|GHOST|MAGMA|PAT|"
    r"RFF|RFR|CNV|CTM|USAF|NATO|GAFE|OOZE|SKULL|ANON|RNZAF|RAAF|"
    r"RRR|RRL|KAF|IAF|ARMYAIR)",
    re.IGNORECASE,
)

# Maximum trail positions kept per aircraft
TRAIL_MAX = 10

# Aircraft considered "expired" after this many seconds without update
FLIGHT_TTL_SECONDS = 60

# Retry backoff for failed requests (seconds)
_BACKOFF = [1, 2, 5, 10, 30]


class OpenSkyIngestionService(BaseIngestionService):
    """
    Polls OpenSky every 10 s, parses state vectors, upserts GlobeEvents.

    In-memory trail dict keeps the last ``TRAIL_MAX`` positions per ICAO24
    so the frontend can render the flight path without extra DB queries.
    """

    source_name = "flight"
    poll_interval_seconds = 10

    def __init__(self) -> None:
        super().__init__()
        # icao24 → deque of {"lat", "lng", "alt", "ts"} (most-recent last)
        self._trails: dict[str, deque] = {}
        self._http: httpx.AsyncClient | None = None

    # ── HTTP client (lazy, shared across polls) ───────────────────────────────

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            auth = None
            if settings.opensky_username and settings.opensky_password:
                auth = (settings.opensky_username, settings.opensky_password)
            self._http = httpx.AsyncClient(
                auth=auth,
                timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0),
                headers={"User-Agent": "nexus-globe/1.0"},
            )
        return self._http

    # ── fetch_raw ────────────────────────────────────────────────────────────

    async def fetch_raw(self) -> Any:
        """
        GET OpenSky states/all with retry + exponential backoff.
        Returns the parsed JSON dict or None on persistent failure.
        """
        for attempt, wait in enumerate([0] + _BACKOFF, start=1):
            if wait:
                await asyncio.sleep(wait)
            try:
                resp = await self._client().get(OPENSKY_URL)
                if resp.status_code == 429:
                    self.logger.warning(
                        "[opensky] Rate-limited (429) — attempt %d", attempt
                    )
                    continue
                resp.raise_for_status()
                data = resp.json()
                states = data.get("states") or []
                self.logger.info(
                    "[opensky] Fetched %d state vectors", len(states)
                )
                return data
            except httpx.TimeoutException:
                self.logger.warning("[opensky] Timeout on attempt %d", attempt)
            except httpx.HTTPStatusError as exc:
                self.logger.warning("[opensky] HTTP %s on attempt %d", exc.response.status_code, attempt)
            except Exception as exc:
                self.logger.warning("[opensky] Fetch error attempt %d: %s", attempt, exc)

        self.logger.error("[opensky] All fetch attempts failed — skipping cycle")
        return None

    # ── normalize ────────────────────────────────────────────────────────────

    async def normalize(self, raw: Any) -> list[dict]:
        """Parse state vectors into GlobeEvent-compatible dicts."""
        if not raw or not raw.get("states"):
            return []

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=FLIGHT_TTL_SECONDS)
        events: list[dict] = []

        for sv in raw["states"]:
            # ── Extract fields ───────────────────────────────────────────
            icao24: str = (sv[0] or "").strip().lower()
            callsign: str = (sv[1] or "").strip() or "UNKNOWN"
            origin_country: str = sv[2] or ""
            longitude: float | None = sv[5]
            latitude: float | None = sv[6]
            baro_alt: float | None = sv[7]
            on_ground: bool = bool(sv[8])
            velocity_ms: float | None = sv[9]   # m/s
            true_track: float | None = sv[10]
            geo_alt: float | None = sv[13]
            squawk: str | None = sv[14]

            # Skip if no position fix
            if latitude is None or longitude is None:
                continue

            # On-ground aircraft can be filtered (configurable — keep for now)
            # if on_ground:
            #     continue

            # ── Derived values ───────────────────────────────────────────
            # Prefer geometric altitude; fall back to barometric
            altitude_m = geo_alt if geo_alt is not None else baro_alt

            # Convert m/s → km/h
            speed_kmh = (velocity_ms * 3.6) if velocity_ms is not None else None

            # Military detection by callsign prefix
            severity = 2 if _MILITARY_RE.match(callsign) else 1

            # ── Trail management ─────────────────────────────────────────
            trail_deque = self._trails.setdefault(icao24, deque(maxlen=TRAIL_MAX))
            trail_deque.append({
                "lat": latitude,
                "lng": longitude,
                "alt": altitude_m,
                "ts":  now.isoformat(),
            })
            trail = list(trail_deque)

            events.append({
                "event_type":  "flight",
                "category":    "aviation",
                "title":       callsign,
                "description": f"{callsign} — {origin_country}",
                "latitude":    latitude,
                "longitude":   longitude,
                "altitude_m":  altitude_m,
                "heading_deg": true_track,
                "speed_kmh":   speed_kmh,
                "severity":    severity,
                "source":      "opensky",
                "source_url":  f"https://opensky-network.org/aircraft-profile?icao24={icao24}",
                "source_id":   icao24,
                "metadata": {
                    "icao24":         icao24,
                    "callsign":       callsign,
                    "origin_country": origin_country,
                    "on_ground":      on_ground,
                    "squawk":         squawk,
                    "baro_altitude":  baro_alt,
                },
                "trail":       trail,
                "expires_at":  expires_at,
            })

        self.logger.info(
            "[opensky] Normalised %d flights (from %d state vectors)",
            len(events),
            len(raw["states"]),
        )
        return events

