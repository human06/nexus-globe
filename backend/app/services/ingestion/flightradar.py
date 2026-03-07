"""FlightRadar24 flight ingestion service.

Uses the unofficial FlightRadar24API Python library to fetch live aircraft
state vectors including origin and destination airport IATA codes.

⚠  The FlightRadar24 library reverse-engineers FR24's public web API.
   It is suitable for personal/dev use; review FR24's ToS before deploying
   in a commercial environment.

Flight attributes from FR24 API:
  icao_24bit         — ICAO 24-bit transponder address (hex)
  callsign           — ATC callsign (e.g. "BAW123")
  number             — Flight number (e.g. "BA123")
  aircraft_code      — ICAO aircraft type (e.g. "B738")
  registration       — Tail number (e.g. "G-EUPT")
  latitude/longitude — WGS-84
  altitude           — feet (MSL)
  ground_speed       — knots
  heading            — degrees clockwise from north
  vertical_speed     — ft/min
  on_ground          — bool
  origin_airport_iata       — 3-letter IATA (e.g. "LHR"), may be empty
  destination_airport_iata  — 3-letter IATA (e.g. "JFK"), may be empty
  airline_iata       — 2-letter airline IATA (e.g. "BA")
  airline_icao       — 3-letter airline ICAO (e.g. "BAW")
"""
from __future__ import annotations

import asyncio
import math
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections import deque
from typing import Any

from app.services.ingestion.base import BaseIngestionService

# Maximum trail positions kept per aircraft
TRAIL_MAX = 10

# Live events expire after this many seconds
FLIGHT_TTL_SECONDS = 1800  # 30 minutes

# Demo events expire sooner so they vanish once real data arrives
DEMO_FLIGHT_TTL_SECONDS = 90

# Maximum flights to ingest per cycle (FR24 returns 15 k+; cap to keep
# things snappy and not hammer Postgres)
MAX_FLIGHTS = 2000

# Seconds between live polls (be polite to the unofficial API)
POLL_INTERVAL = 30

# Military callsign prefixes
_MILITARY_RE = re.compile(
    r"^(RCH|REACH|JAKE|DUKE|ROCKY|SPAR|IRON|VENUS|GHOST|MAGMA|PAT|"
    r"RFF|RFR|CNV|CTM|USAF|NATO|GAFE|OOZE|SKULL|ANON|RNZAF|RAAF|"
    r"RRR|RRL|KAF|IAF|ARMYAIR)",
    re.IGNORECASE,
)

# ── Demo fleet ────────────────────────────────────────────────────────────────

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
]
_DEMO_CALLSIGNS = [
    ("BAW", "BA"), ("UAL", "UA"), ("DAL", "DL"), ("AAL", "AA"),
    ("AFR", "AF"), ("DLH", "LH"), ("KLM", "KL"), ("SWA", "WN"),
    ("EZY", "U2"), ("RYR", "FR"), ("UAE", "EK"), ("SIA", "SQ"),
    ("QFA", "QF"), ("JAL", "JL"), ("ANA", "NH"), ("ETH", "ET"),
]
_DEMO_ROUTES = [
    ("LHR", "JFK"), ("JFK", "LHR"), ("CDG", "LAX"), ("LAX", "NRT"),
    ("DXB", "LHR"), ("SIN", "LHR"), ("SYD", "LAX"), ("ORD", "LHR"),
    ("FRA", "JFK"), ("AMS", "JFK"), ("GRU", "LIS"), ("NRT", "SFO"),
    ("ICN", "LAX"), ("DEL", "LHR"), ("HND", "CDG"), ("BKK", "LHR"),
    ("MAD", "JFK"), ("ZRH", "ORD"), ("DEN", "SEA"), ("ATL", "MCO"),
]
_DEMO_AIRCRAFT = ["B738", "A320", "B77W", "A333", "B789", "A321", "E190", "A388"]


@dataclass
class _DemoAC:
    icao24: str
    callsign: str
    number: str
    aircraft_code: str
    origin: str
    destination: str
    lat: float
    lng: float
    heading: float
    speed_kts: float    # knots
    altitude_ft: float  # feet

    def tick(self, dt_s: float) -> None:
        dt_h = dt_s / 3600.0
        d_km = (self.speed_kts * 1.852) * dt_h
        h_rad = math.radians(self.heading)
        self.lat += (d_km / 111.0) * math.cos(h_rad)
        self.lat = max(-85.0, min(85.0, self.lat))
        cos_lat = math.cos(math.radians(self.lat)) or 1e-9
        self.lng += (d_km / (111.0 * cos_lat)) * math.sin(h_rad)
        self.lng = ((self.lng + 180.0) % 360.0) - 180.0


# ── Service ───────────────────────────────────────────────────────────────────

class FlightRadarIngestionService(BaseIngestionService):
    """Ingest live flights from FlightRadar24 (unofficial API).

    Falls back to an animated demo fleet on any API failure so the globe
    always shows aircraft.
    """

    source_name = "flight"
    poll_interval_seconds = POLL_INTERVAL

    def __init__(self) -> None:
        super().__init__()
        self._trails: dict[str, deque] = {}
        self._demo_fleet: list[_DemoAC] = []
        self._fr_api = None          # lazy-initialised inside thread

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_api(self):
        """Return a cached FlightRadar24API instance (synchronous, thread-safe)."""
        if self._fr_api is None:
            from FlightRadar24 import FlightRadar24API
            self._fr_api = FlightRadar24API()
        return self._fr_api

    def _fetch_sync(self):
        """Blocking call — run inside asyncio.to_thread()."""
        api = self._get_api()
        flights = api.get_flights()
        return flights[:MAX_FLIGHTS]

    # ── Demo fleet ────────────────────────────────────────────────────────────

    def _ensure_demo_fleet(self) -> None:
        if self._demo_fleet:
            return
        rng = random.Random(42)
        idx = 0
        for (clat, clng, slat, slng, count) in _DEMO_CORRIDORS:
            for _ in range(count):
                lat = max(-85.0, min(85.0, clat + rng.uniform(-slat, slat)))
                lng_raw = clng + rng.uniform(-slng, slng)
                lng = ((lng_raw + 180.0) % 360.0) - 180.0
                cs_icao, al_iata = rng.choice(_DEMO_CALLSIGNS)
                num = rng.randint(1, 999)
                origin, dest = rng.choice(_DEMO_ROUTES)
                self._demo_fleet.append(_DemoAC(
                    icao24=f"fr24{idx:04x}",
                    callsign=f"{cs_icao}{num}",
                    number=f"{al_iata}{num}",
                    aircraft_code=rng.choice(_DEMO_AIRCRAFT),
                    origin=origin,
                    destination=dest,
                    lat=lat,
                    lng=lng,
                    heading=rng.uniform(0, 360),
                    speed_kts=rng.uniform(380, 510),
                    altitude_ft=rng.uniform(25_000, 41_000),
                ))
                idx += 1
        self.logger.info("[flightradar] Demo fleet: %d aircraft", len(self._demo_fleet))

    def _tick_demo(self) -> list[dict]:
        """Advance demo fleet and return pseudo-FR24 dicts."""
        self._ensure_demo_fleet()
        rows = []
        for ac in self._demo_fleet:
            ac.tick(self.poll_interval_seconds)
            rows.append({
                "icao_24bit": ac.icao24,
                "callsign": ac.callsign,
                "number": ac.number,
                "aircraft_code": ac.aircraft_code,
                "registration": "",
                "latitude": ac.lat,
                "longitude": ac.lng,
                "altitude": ac.altitude_ft,
                "ground_speed": ac.speed_kts,
                "heading": ac.heading,
                "vertical_speed": 0,
                "on_ground": False,
                "origin_airport_iata": ac.origin,
                "destination_airport_iata": ac.destination,
                "airline_iata": ac.callsign[:2],
                "airline_icao": ac.callsign[:3],
                "_demo": True,
            })
        return rows

    # ── BaseIngestionService interface ────────────────────────────────────────

    async def fetch_raw(self) -> Any:
        """Fetch flights from FR24; return demo list on any failure."""
        try:
            flights = await asyncio.to_thread(self._fetch_sync)
            count = len(flights)
            self.logger.info("[flightradar] Fetched %d live flights", count)
            # Convert Flight objects to dicts so normalize() can work uniformly
            rows = []
            for f in flights:
                rows.append({
                    "icao_24bit":              getattr(f, "icao_24bit", "") or "",
                    "callsign":                (getattr(f, "callsign", "") or "").strip(),
                    "number":                  (getattr(f, "number", "") or "").strip(),
                    "aircraft_code":           (getattr(f, "aircraft_code", "") or "").strip(),
                    "registration":            (getattr(f, "registration", "") or "").strip(),
                    "latitude":                getattr(f, "latitude", None),
                    "longitude":               getattr(f, "longitude", None),
                    "altitude":                getattr(f, "altitude", None),        # feet
                    "ground_speed":            getattr(f, "ground_speed", None),    # knots
                    "heading":                 getattr(f, "heading", None),
                    "vertical_speed":          getattr(f, "vertical_speed", None),
                    "on_ground":               bool(getattr(f, "on_ground", False)),
                    "origin_airport_iata":     (getattr(f, "origin_airport_iata", "") or "").strip(),
                    "destination_airport_iata": (getattr(f, "destination_airport_iata", "") or "").strip(),
                    "airline_iata":            (getattr(f, "airline_iata", "") or "").strip(),
                    "airline_icao":            (getattr(f, "airline_icao", "") or "").strip(),
                    "_demo": False,
                })
            return rows

        except Exception as exc:
            self.logger.warning("[flightradar] Fetch failed (%s) — serving demo flights", exc)
            return self._tick_demo()

    async def normalize(self, raw: Any) -> list[dict]:
        """Convert raw FR24 rows into GlobeEvent-compatible dicts."""
        if not raw:
            return []

        now = datetime.now(timezone.utc)
        events: list[dict] = []

        for row in raw:
            lat = row.get("latitude")
            lng = row.get("longitude")
            if lat is None or lng is None:
                continue
            try:
                lat = float(lat)
                lng = float(lng)
            except (TypeError, ValueError):
                continue

            icao24   = str(row.get("icao_24bit") or "").lower()
            callsign = str(row.get("callsign") or "").strip()
            number   = str(row.get("number") or "").strip()
            ac_type  = str(row.get("aircraft_code") or "").strip()
            reg      = str(row.get("registration") or "").strip()
            origin   = str(row.get("origin_airport_iata") or "").strip().upper()
            dest     = str(row.get("destination_airport_iata") or "").strip().upper()

            # Prefer flight number as title; fall back to callsign
            title = number or callsign or icao24.upper()

            # Route string for description
            if origin and dest:
                route = f"{origin} → {dest}"
            elif origin:
                route = f"{origin} → …"
            elif dest:
                route = f"… → {dest}"
            else:
                route = ""

            is_demo = bool(row.get("_demo"))

            # Altitude: FR24 returns feet → metres
            alt_ft  = row.get("altitude")
            alt_m   = float(alt_ft) * 0.3048 if alt_ft is not None else None

            # Speed: knots → km/h
            spd_kts = row.get("ground_speed")
            spd_kmh = float(spd_kts) * 1.852 if spd_kts is not None else None

            heading = row.get("heading")
            on_ground = bool(row.get("on_ground", False))

            severity = 2 if _MILITARY_RE.match(callsign or "") else 1

            # Trail
            trail_dq = self._trails.setdefault(icao24 or title, deque(maxlen=TRAIL_MAX))
            trail_dq.append({"lat": lat, "lng": lng, "alt": alt_m, "ts": now.isoformat()})

            ttl = DEMO_FLIGHT_TTL_SECONDS if is_demo else FLIGHT_TTL_SECONDS
            expires_at = now + timedelta(seconds=ttl)

            events.append({
                "event_type":  "flight",
                "category":    "aviation",
                "title":       title,
                "description": f"{title}  {route}".strip() + (" (demo)" if is_demo else ""),
                "latitude":    lat,
                "longitude":   lng,
                "altitude_m":  alt_m,
                "heading_deg": float(heading) if heading is not None else None,
                "speed_kmh":   spd_kmh,
                "severity":    severity,
                "source":      "flightradar24",
                "source_url":  f"https://www.flightradar24.com/{number or icao24}" if not is_demo else None,
                "source_id":   icao24 or title.lower(),
                "metadata": {
                    "icao24":       icao24,
                    "callsign":     callsign,
                    "number":       number,
                    "aircraft":     ac_type,
                    "registration": reg,
                    "origin":       origin,
                    "destination":  dest,
                    "route":        route,
                    "on_ground":    on_ground,
                    "demo":         is_demo,
                },
                "trail":      list(trail_dq),
                "expires_at": expires_at,
            })

        label = "demo" if (raw and raw[0].get("_demo")) else "live"
        self.logger.info("[flightradar] Normalised %d %s flights", len(events), label)
        return events
