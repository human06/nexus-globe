"""OpenSky Network ADS-B flight ingestion service — Story 1.5.

Polls https://opensky-network.org/api/states/all every 15 seconds,
normalises aircraft state vectors into GlobeEvents, and hands them to
the base class for upsert + Redis publish.

When the OpenSky API returns 429 (IP rate-limited), the service falls back
to a simulated demo fleet so flights always appear on the globe.

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
import math
import random
import re
from dataclasses import dataclass, field
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
FLIGHT_TTL_SECONDS = 1800  # 30 minutes — survives rate-limit cooldowns & restarts

# Demo flights get a short TTL so they disappear quickly when real data arrives
DEMO_FLIGHT_TTL_SECONDS = 90

# How long (seconds) to pause all requests after a 429
_RATE_LIMIT_COOLDOWN = 120

# ── Demo fleet configuration ──────────────────────────────────────────────────
# (center_lat, center_lng, spread_lat, spread_lng, count) — major corridors
_DEMO_CORRIDORS = [
    (52,  -30,  8, 28, 50),   # North Atlantic
    (35,  145, 10, 18, 40),   # East Asia / Japan
    (50,   10, 12, 22, 60),   # Europe
    (35,  -96, 10, 22, 55),   # US domestic
    (20,   80, 10, 25, 35),   # South Asia
    (25,   52,  8, 16, 30),   # Middle East
    (-25,  25, 10, 22, 20),   # Africa
    (-30, 145,  6, 12, 20),   # Australia
    (-5,  -55,  8, 22, 20),   # South America
    (35, -120,  8, 14, 25),   # US West Coast
    (55,   80,  6, 30, 20),   # Russia / Siberia
]
_DEMO_CALLSIGN_PREFIXES = [
    "UAL", "DAL", "AAL", "SWA", "BAW", "AFR", "DLH", "KLM",
    "EZY", "RYR", "UAE", "SIA", "CCA", "CSN", "JAL", "ANA",
    "QFA", "ETH", "THA", "TRK", "FIN", "TAP", "IBE", "AZA",
]


@dataclass
class _DemoAircraft:
    icao24: str
    callsign: str
    lat: float
    lng: float
    heading: float          # degrees clockwise from north
    speed_kmh: float
    altitude_m: float

    def tick(self, dt_seconds: float) -> None:
        """Advance position by one poll interval."""
        dt_h = dt_seconds / 3600.0
        d_km = self.speed_kmh * dt_h
        heading_rad = math.radians(self.heading)
        lat_r = math.radians(self.lat)
        self.lat += (d_km / 111.0) * math.cos(heading_rad)
        cos_lat = math.cos(lat_r) or 1e-9
        self.lng += (d_km / (111.0 * cos_lat)) * math.sin(heading_rad)
        # Clamp lat, wrap lng
        self.lat = max(-85.0, min(85.0, self.lat))
        self.lng = ((self.lng + 180.0) % 360.0) - 180.0

    def to_state_vector(self) -> list:
        """Return an OpenSky-format state vector list (indices 0-16)."""
        return [
            self.icao24,        # 0  icao24
            self.callsign,      # 1  callsign
            "Demo",             # 2  origin_country
            None,               # 3  time_position
            None,               # 4  last_contact
            self.lng,           # 5  longitude
            self.lat,           # 6  latitude
            self.altitude_m,    # 7  baro_altitude
            False,              # 8  on_ground
            self.speed_kmh / 3.6,  # 9  velocity (m/s)
            self.heading,       # 10 true_track
            0.0,                # 11 vertical_rate
            None,               # 12 sensors
            self.altitude_m,    # 13 geo_altitude
            None,               # 14 squawk
            False,              # 15 spi
            0,                  # 16 position_source (ADS-B)
        ]


class OpenSkyIngestionService(BaseIngestionService):
    """
    Polls OpenSky every 15 s, parses state vectors, upserts GlobeEvents.

    Single attempt per cycle (no retry loop).  When a 429 is received the
    service sets ``_blocked_until`` and skips every subsequent poll cycle
    until the cooldown expires — this prevents the retry storm that causes
    prolonged rate-limiting.

    When blocked, ``fetch_raw()`` returns a synthetic demo dataset so the
    globe always displays live-looking flights even during rate-limit windows.
    """

    source_name = "flight"
    poll_interval_seconds = 15

    def __init__(self) -> None:
        super().__init__()
        # icao24 → deque of {"lat", "lng", "alt", "ts"} (most-recent last)
        self._trails: dict[str, deque] = {}
        self._http: httpx.AsyncClient | None = None
        # Set to a future datetime when a 429 is received; cycles are skipped
        # until datetime.now() > _blocked_until
        self._blocked_until: datetime | None = None
        # Demo fleet — initialised lazily on first blocked poll
        self._demo_fleet: list[_DemoAircraft] = []

    # ── Demo fleet helpers ────────────────────────────────────────────────────

    def _ensure_demo_fleet(self) -> None:
        """Build the demo fleet once; subsequent calls are no-ops."""
        if self._demo_fleet:
            return
        rng = random.Random(12345)  # fixed seed → deterministic starting positions
        idx = 0
        for (clat, clng, slat, slng, count) in _DEMO_CORRIDORS:
            for _ in range(count):
                lat = clat + rng.uniform(-slat, slat)
                lng = clng + rng.uniform(-slng, slng)
                lat = max(-85.0, min(85.0, lat))
                lng = ((lng + 180.0) % 360.0) - 180.0
                prefix = rng.choice(_DEMO_CALLSIGN_PREFIXES)
                callsign = f"{prefix}{rng.randint(1, 9999):04d}"
                self._demo_fleet.append(_DemoAircraft(
                    icao24=f"demo{idx:04x}",
                    callsign=callsign,
                    lat=lat,
                    lng=lng,
                    heading=rng.uniform(0, 360),
                    speed_kmh=rng.uniform(650, 950),
                    altitude_m=rng.uniform(8000, 12500),
                ))
                idx += 1
        self.logger.info("[opensky] Demo fleet initialised with %d aircraft", len(self._demo_fleet))

    def _tick_demo_fleet(self) -> dict:
        """Advance all demo aircraft one poll interval and return fake API response."""
        self._ensure_demo_fleet()
        for ac in self._demo_fleet:
            ac.tick(self.poll_interval_seconds)
        return {"states": [ac.to_state_vector() for ac in self._demo_fleet], "_demo": True}

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
        Single GET attempt against OpenSky states/all per scheduled cycle.

        On 429:  records a cooldown timestamp and returns demo data —
                 no retry loop that would keep hammering the API.
        Returns the parsed JSON dict on success (or demo dict when blocked).
        """
        now = datetime.now(timezone.utc)

        # Still inside a rate-limit cooldown window — serve demo data
        if self._blocked_until and now < self._blocked_until:
            remaining = int((self._blocked_until - now).total_seconds())
            self.logger.info(
                "[opensky] Cooling down — %ds remaining, serving demo flights", remaining
            )
            return self._tick_demo_fleet()

        try:
            resp = await self._client().get(OPENSKY_URL)

            if resp.status_code == 429:
                self._blocked_until = now + timedelta(seconds=_RATE_LIMIT_COOLDOWN)
                self.logger.warning(
                    "[opensky] Rate-limited (429) — backing off %ds until %s, serving demo flights",
                    _RATE_LIMIT_COOLDOWN,
                    self._blocked_until.strftime("%H:%M:%S UTC"),
                )
                return self._tick_demo_fleet()

            resp.raise_for_status()
            data = resp.json()
            states = data.get("states") or []
            self.logger.info("[opensky] Fetched %d real state vectors", len(states))
            # Clear any stale cooldown on success
            self._blocked_until = None
            return data

        except httpx.TimeoutException:
            self.logger.warning("[opensky] Request timed out — serving demo flights")
        except httpx.HTTPStatusError as exc:
            self.logger.warning("[opensky] HTTP %s — serving demo flights", exc.response.status_code)
        except Exception as exc:
            self.logger.warning("[opensky] Fetch error — serving demo flights: %s", exc)

        return self._tick_demo_fleet()

    # ── normalize ────────────────────────────────────────────────────────────

    async def normalize(self, raw: Any) -> list[dict]:
        """Parse state vectors into GlobeEvent-compatible dicts."""
        if not raw or not raw.get("states"):
            return []

        is_demo = bool(raw.get("_demo"))
        now = datetime.now(timezone.utc)
        ttl = DEMO_FLIGHT_TTL_SECONDS if is_demo else FLIGHT_TTL_SECONDS
        expires_at = now + timedelta(seconds=ttl)
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
                "description": f"{callsign} — {origin_country}" + (" (demo)" if is_demo else ""),
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
                    "demo":           is_demo,
                },
                "trail":       trail,
                "expires_at":  expires_at,
            })

        self.logger.info(
            "[opensky] Normalised %d %s flights (from %d state vectors)",
            len(events),
            "demo" if is_demo else "real",
            len(raw["states"]),
        )
        return events

