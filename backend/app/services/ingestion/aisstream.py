"""AISstream.io Ship Tracking Ingestion — Story 2.6 (AISstream variant).

Streams live AIS vessel positions via WebSocket from aisstream.io.

Free tier: sign in at https://aisstream.io/authenticate (GitHub OAuth),
then generate a key at https://aisstream.io/apikeys.

Protocol:
  wss://stream.aisstream.io/v0/stream
  - Send a JSON subscription message within 3 s of connecting.
  - Receive a stream of {MessageType, MetaData, Message} JSON objects.

Each poll cycle this service:
  1. Opens the WSS connection.
  2. Subscribes to PositionReport + ShipStaticData, globally.
  3. Collects messages for _COLLECT_SECS seconds (default 30).
  4. Closes the connection and normalises the accumulated vessel state.

DEMO FALLBACK
=============
If the live WebSocket connection fails (e.g. the server is unreachable
from this IP range), the service falls back to ~80 built-in demo vessels
spread across global shipping lanes. Positions advance each cycle based
on each vessel heading and speed. Demo vessels are labelled with
source="aisstream_demo" so they can be filtered out once a real feed
is available.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)

_AISSTREAM_URL   = "wss://stream.aisstream.io/v0/stream"
_COLLECT_SECS    = 30
_TRAIL_MAXLEN    = 20
_WS_OPEN_TIMEOUT = 30    # seconds for WebSocket opening handshake (legacy API needs more time)

_SHIP_TYPES: list[tuple[range, str]] = [
    (range(30, 40), "fishing"),
    (range(50, 60), "special"),
    (range(60, 70), "passenger"),
    (range(70, 80), "cargo"),
    (range(80, 90), "tanker"),
]

# fmt: off
# Each row: (mmsi, name, lat, lng, heading_deg, sog_kts, ais_type, destination)
_DEMO_VESSELS: list[tuple] = [
    # North Atlantic
    (219012001, "MAERSK ANTWERP",       45.2,  -28.5, 340, 16.5, 79, "HAMBURG"),
    (219012002, "EVERGREEN ATLAS",      38.8,  -22.3, 335, 15.0, 71, "ROTTERDAM"),
    (538012003, "CMA CGM PARIS",        50.1,  -15.2, 280, 17.0, 79, "LE HAVRE"),
    (636012004, "MSC VENICE",           42.5,  -32.1, 100,  0.5, 71, "NEW YORK"),
    (219012005, "HAPAG ROTTERDAM",      55.0,  -12.0, 175, 14.0, 79, "HAMBURG"),
    (477012006, "YANGMING COURAGE",     48.3,  -18.5, 270, 15.5, 71, "NEW YORK"),
    (538012007, "PIL ADRIATIC",         35.3,  -38.0, 340, 14.0, 71, "VALENCIA"),
    (636012008, "COSCO BEIJING",        40.0,  -45.0,  90, 15.0, 71, "NEW YORK"),
    # English Channel / North Sea
    (219012009, "NORDIC ANNE",          51.2,    1.5, 280, 18.0, 79, "FELIXSTOWE"),
    (246012010, "STENA FORERUNNER",     52.0,    3.8, 260, 13.0, 70, "HARWICH"),
    (219012011, "DFDS VICTORIA",        56.1,   10.3, 185, 20.0, 71, "GOTHENBURG"),
    (219012012, "FRISIAN SPRING",       53.5,    6.2, 270, 12.0, 79, "BREMERHAVEN"),
    # Mediterranean / Suez
    (636012013, "VALEMAX OCEAN",        35.8,   14.5, 110, 14.5, 89, "PORT SAID"),
    (636012014, "BOURBON LIBERTY",      36.5,    5.2,  90, 12.0, 89, "AUGUSTA"),
    (636012015, "CMA CGM MARSEILLE",    37.0,   10.8,  80, 15.5, 71, "PIRAEUS"),
    (255012016, "ATLANTIC CARRIER",     30.2,   32.1,  90,  0.0, 71, "SUEZ"),
    (636012017, "ARIANA GAS",           27.5,   34.0, 145, 14.0, 80, "JEDDAH"),
    (636012018, "AL MARIYAH",           22.3,   38.8, 165, 13.5, 80, "ADEN"),
    # Persian Gulf / Indian Ocean
    (477012019, "EURONAV LOTUS",        24.8,   56.5, 270,  0.5, 89, "JEBEL ALI"),
    (636012020, "VLCC PACIFIC LION",    20.5,   62.8, 200, 12.0, 89, "SINGAPORE"),
    (638012021, "DIANA Z",              10.2,   63.5, 140, 14.0, 79, "MUMBAI"),
    (636012022, "MAERSK DUBAI",          1.8,   79.5, 270, 16.0, 79, "COLOMBO"),
    (636012023, "NYK STELLA",           12.5,   52.8, 145, 15.0, 71, "SINGAPORE"),
    # Southeast Asia / Malacca
    (477012024, "CSCL GLOBE",            3.2,  102.0, 320, 15.0, 71, "SHANGHAI"),
    (477012025, "OOCL EUROPE",           5.8,  105.2, 300, 16.0, 71, "HONG KONG"),
    (636012026, "PELICAN",               1.2,  103.5, 140, 12.0, 79, "BATAM"),
    (566012027, "SINGAPORE BULKER",      1.5,  104.0,  45, 10.0, 71, "JURONG"),
    (477012028, "YANG MING WITNESS",     7.5,  108.5,  20, 14.5, 71, "KAOHSIUNG"),
    # East Asia
    (477012029, "EVERGREEN GLORY",      24.0,  122.0, 350, 15.0, 71, "KEELUNG"),
    (431012030, "NYK THEMIS",           34.5,  138.0, 200, 17.0, 71, "YOKOHAMA"),
    (477012031, "COSCO SHIPPING GEMINI",28.5,  125.0,  60, 16.0, 71, "BUSAN"),
    (431012032, "MOL PRESENCE",         35.8,  141.5, 355, 15.5, 71, "TOKYO"),
    (441012033, "HMM OSLO",             37.5,  128.0, 180, 14.0, 71, "BUSAN"),
    # Trans-Pacific
    (477012034, "OOCL HONG KONG",       38.0,  178.0,  80, 17.5, 71, "LONG BEACH"),
    (538012035, "MSC ELOANE",           42.0, -160.0,  90, 16.0, 71, "LOS ANGELES"),
    (636012036, "PRIDE OF PACIFIC",     35.0, -140.0,  95, 15.0, 71, "SAN PEDRO"),
    (636012037, "COSCO PACIFIC",        30.0, -125.5, 100, 14.5, 79, "MANZANILLO"),
    # US East / Gulf
    (338012038, "HORIZON FALCON",       40.2,  -73.5, 200, 12.0, 79, "BALTIMORE"),
    (338012039, "MSC NEW YORK",         37.0,  -65.5, 300, 15.0, 71, "NEW YORK"),
    (338012040, "ATLANTIC STAR",        25.5,  -79.8,  30, 14.0, 71, "CHARLESTON"),
    (338012041, "FEDERAL CARIBOU",      28.2,  -88.5, 170, 13.0, 71, "HOUSTON"),
    (338012042, "ENERGY SEAS",          29.5,  -88.2,   0,  1.0, 89, "OFFSHORE"),
    # Caribbean / Panama
    (636012043, "CARTAGENA EXPRESS",    18.5,  -72.5, 240, 14.0, 71, "COLON"),
    (216012044, "FESCO CONSUL",         13.2,  -60.3, 280, 13.5, 71, "TRINIDAD"),
    (636012045, "NORDLINK",              8.5,  -77.2, 270, 16.0, 71, "BALBOA"),
    # South America
    (710012046, "RIO NAVEGADOR",       -23.0,  -42.8, 100, 14.0, 71, "SANTOS"),
    (710012047, "AGULHAS BULKER",      -33.5,  -18.0,  60, 13.5, 71, "CAPE TOWN"),
    # South Atlantic / Africa
    (636012048, "TANKER AZALEA",        -5.5,   -5.5, 190, 13.0, 89, "DURBAN"),
    (710012049, "PETROBRAS SPIRIT",    -22.5,  -38.0, 200, 12.5, 89, "SANTOS"),
    (636012050, "CAPE EXPRESS",        -34.5,   18.5,  80, 14.0, 71, "DURBAN"),
    (636012051, "MSC AGADIR",           32.0,   -8.5, 340, 15.5, 71, "ALGECIRAS"),
    # West Africa
    (636012052, "DEEP OIL II",           5.5,    3.0, 270,  2.0, 52, "OFFSHORE"),
    (636012053, "BOURBON OFFSHORE",      6.2,   -1.5,  90,  8.0, 52, "TEMA"),
    # Cruise ships
    (215012054, "MSC BELLISSIMA",       43.3,    5.5, 250, 20.0, 60, "BARCELONA"),
    (311012055, "CARNIVAL TRIUMPH",     25.8,  -79.1, 180, 22.0, 60, "NASSAU"),
    (610012056, "COSTA FORTUNA",        37.8,   23.5,  90, 18.5, 60, "PIRAEUS"),
    (215012057, "CELEBRITY APEX",       40.5,  -64.0, 260, 21.0, 60, "NEW YORK"),
    # Fishing vessels
    (219012058, "STELLA MARIS",         64.5,  -22.0, 180,  6.0, 30, "REYKJAVIK"),
    (259012059, "SJOHOLM",              63.0,    5.5, 270,  5.5, 30, "BERGEN"),
    (257012060, "HAVFISK",              70.8,   25.5,  10,  4.0, 30, "TROMSO"),
    (503012061, "AUST FISHERIES",      -35.2,  149.5, 100,  5.0, 30, "ALBANY"),
    (431012062, "DAIEI MARU",           45.5,  145.8,  20,  7.5, 30, "NEMURO"),
    (224012063, "NUEVO RUMBO",          43.5,   -9.0, 215,  6.5, 30, "VIGO"),
    # Bulk carriers
    (636012064, "CAPE GARLAND",        -18.0,   38.5,  15, 13.0, 71, "BEIRA"),
    (477012065, "GREAT PEARL",          16.5,   60.2, 250, 12.0, 71, "ADEN"),
    (636012066, "ORION HIGHWAY",       -28.5,   30.8, 200, 14.0, 71, "DURBAN"),
    (636012067, "BULK BERMUDA",         38.0,  -35.0, 100, 13.5, 71, "DAKAR"),
    (636012068, "CORONA BULKER",        -5.2,   50.8,  90, 12.5, 71, "COLOMBO"),
    # Ferries
    (249012069, "STENA BALTICA",        57.2,   15.2, 320, 17.0, 70, "TRELLEBORG"),
    (230012070, "FINNCLIPPER",          60.5,   20.5, 270, 22.0, 70, "STOCKHOLM"),
    (246012071, "DFDS PEARL SEAWAYS",   57.6,   10.6, 180, 19.5, 70, "COPENHAGEN"),
    # Mixed
    (636012072, "SWIFT SUPPLIER",       22.5,   59.5,  10,  9.5, 52, "SOHAR"),
    (636012073, "PACIFIC EMERALD",       8.0,  125.0, 180, 15.0, 71, "DAVAO"),
    (477012074, "CHINA PIONEER",        32.5,  121.8,  40, 14.0, 71, "NINGBO"),
    (218012075, "WESER TRADER",         54.0,    8.5,  90, 11.0, 71, "HAMBURG"),
    (249012076, "NEPTUNE FLAG",         35.2,   23.3, 280, 13.5, 71, "IRAKLIO"),
    (636012077, "STAR QUEST",          -43.5,   25.0,  60, 14.0, 71, "FREMANTLE"),
    (477012078, "MINSHAN",             -12.5,   65.5,  90, 15.0, 71, "SINGAPORE"),
    (538012079, "WILHELMSEN MASTER",    52.8,  -35.5, 260, 14.5, 71, "NEW YORK"),
    (636012080, "OLYMPIC FLAG",         -8.0,  115.0, 200, 13.0, 71, "DARWIN"),
]
# fmt: on


def _classify(type_code: int | None) -> str:
    if type_code is None:
        return "ship"
    for rng, label in _SHIP_TYPES:
        if type_code in rng:
            return label
    return "ship"


def _advance_position(
    lat: float, lng: float, heading_deg: float, sog_kts: float, elapsed_s: float
) -> tuple[float, float]:
    """Move (lat, lng) along heading_deg for elapsed_s seconds at sog_kts."""
    if sog_kts <= 0.0 or elapsed_s <= 0.0:
        return lat, lng
    dist_m   = sog_kts * 1852.0 * elapsed_s / 3600.0
    earth_r  = 6_371_000.0
    h_rad    = math.radians(heading_deg)
    delta_lat = (dist_m / earth_r) * math.cos(h_rad)
    delta_lng = (dist_m / (earth_r * math.cos(math.radians(lat)))) * math.sin(h_rad)
    new_lat   = max(-89.9, min(89.9, lat + math.degrees(delta_lat)))
    new_lng   = ((lng + math.degrees(delta_lng)) + 180.0) % 360.0 - 180.0
    return round(new_lat, 5), round(new_lng, 5)


class AISStreamIngestionService(BaseIngestionService):
    """Live vessel tracking via AISstream.io WebSocket feed, with demo fallback."""

    source_name           = "aisstream"
    # 5 minutes — AISstream is a persistent WebSocket feed, not a REST API.
    # Rapid reconnects (60s) hammer Cloudflare's bot scoring and cause the
    # IP to be rate-limited (silent upgrade drop). 300s gives CF time to
    # reset between scheduler cycles while still keeping ships fresh.
    poll_interval_seconds = 300

    def __init__(self) -> None:
        super().__init__()
        self._static:   dict[int, dict]        = {}
        self._trails:   dict[int, deque]        = {}
        self._positions: dict[int, dict]        = {}
        self._demo_positions: dict[int, dict] | None = None
        self._demo_last_updated: float = 0.0

    # ── BaseIngestionService interface ────────────────────────────────────────

    async def fetch_raw(self) -> dict[int, dict] | None:
        from app.config import settings

        api_key = settings.aisstream_api_key
        if not api_key:
            logger.debug("[aisstream] No API key — using demo vessels")
            return self._get_demo_vessels()

        t0 = time.monotonic()
        subscribe_msg = json.dumps({
            "APIKey":             api_key,
            "BoundingBoxes":      [[[-90, -180], [90, 180]]],
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        })

        vessels: dict[int, dict] = {}

        try:
            # Use legacy websockets.connect API — the new asyncio API times out
            # on this server (Cloudflare blocks the upgrade from the new handshake
            # implementation but passes the legacy one with ping_interval=None).
            import websockets  # type: ignore

            async with websockets.connect(
                _AISSTREAM_URL,
                open_timeout=_WS_OPEN_TIMEOUT,
                ping_interval=None,
            ) as ws:
                await ws.send(subscribe_msg)
                deadline = time.monotonic() + _COLLECT_SECS

                while time.monotonic() < deadline:
                    remaining = deadline - time.monotonic()
                    try:
                        raw_msg = await asyncio.wait_for(
                            ws.recv(),
                            timeout=min(remaining + 0.5, 10.0),
                        )
                    except (asyncio.TimeoutError, TimeoutError):
                        break

                    try:
                        msg = json.loads(raw_msg)
                    except json.JSONDecodeError:
                        continue

                    if "error" in msg:
                        logger.warning("[aisstream] Server error: %s", msg["error"])
                        break

                    self._handle_message(msg, vessels)

        except (asyncio.TimeoutError, TimeoutError, OSError) as exc:
            logger.warning("[aisstream] Connection failed (%s) — using demo vessels", exc)
            return self._get_demo_vessels()
        except Exception as exc:
            logger.warning("[aisstream] WebSocket error (%s: %s) — demo", type(exc).__name__, exc)
            return self._get_demo_vessels()

        elapsed = time.monotonic() - t0
        live_count = len(vessels)
        logger.info("[aisstream] Live: %d vessels in %.1fs", live_count, elapsed)
        return vessels if vessels else self._get_demo_vessels()

    async def normalize(self, raw: dict[int, dict] | None) -> list[dict]:
        if not raw:
            return []

        now    = datetime.now(timezone.utc)
        events: list[dict] = []
        type_counts: dict[str, int] = {}
        skipped = 0

        for mmsi, v in raw.items():
            lat = v.get("lat")
            lng = v.get("lng")
            if lat is None or lng is None:
                skipped += 1
                continue

            try:
                lat = float(lat)
                lng = float(lng)
            except (TypeError, ValueError):
                skipped += 1
                continue

            if lat == 0.0 and lng == 0.0:
                skipped += 1
                continue

            sog      = v.get("sog")
            heading  = v.get("heading")
            cog      = v.get("cog")
            name     = (v.get("name") or f"MMSI {mmsi}").strip()
            imo      = v.get("imo")
            callsign = v.get("callsign") or None
            dest     = v.get("destination") or None
            eta_raw  = v.get("eta")
            draught  = v.get("draught")
            dim      = v.get("dim") or {}
            length   = (dim.get("A", 0) + dim.get("B", 0)) or None
            width    = (dim.get("C", 0) + dim.get("D", 0)) or None
            type_code = v.get("type_code")
            category  = _classify(type_code)
            is_demo   = bool(v.get("_demo", False))
            source    = "aisstream_demo" if is_demo else "aisstream"

            if isinstance(heading, (int, float)) and heading >= 360:
                heading = cog

            self._trails.setdefault(mmsi, deque(maxlen=_TRAIL_MAXLEN))
            self._trails[mmsi].appendleft({
                "lat": round(lat, 5),
                "lng": round(lng, 5),
                "ts":  now.isoformat(),
            })
            trail = list(self._trails[mmsi])

            type_counts[category] = type_counts.get(category, 0) + 1

            sog_str  = f"{sog:.1f} kts" if sog is not None else "speed unknown"
            dest_str = f" → {dest}"    if dest else ""
            title    = f"{name} ({category})"[:200]
            desc     = f"{category.title()} vessel{dest_str}. Speed: {sog_str}."
            if is_demo:
                desc += " [DEMO DATA]"

            eta_str: str | None = None
            if isinstance(eta_raw, dict):
                m  = eta_raw.get("Month", 0)
                d  = eta_raw.get("Day", 0)
                h  = eta_raw.get("Hour", 0)
                mn = eta_raw.get("Minute", 0)
                if any([m, d, h, mn]):
                    eta_str = f"{m:02d}-{d:02d} {h:02d}:{mn:02d}Z"

            events.append({
                "event_type":      "ship",
                "category":        category,
                "title":           title,
                "description":     desc,
                "latitude":        round(lat, 5),
                "longitude":       round(lng, 5),
                "altitude_m":      0,
                "heading_deg":     round(heading) if heading is not None else None,
                "speed_kmh":       round(float(sog) * 1.852, 1) if sog is not None else None,
                "severity":        1,
                "source":          source,
                "source_id":       str(mmsi),
                "source_url":      f"https://www.marinetraffic.com/en/ais/details/ships/mmsi:{mmsi}",
                "expires_at":      now + timedelta(seconds=120),
                "needs_geocoding": False,
                "metadata": {
                    "mmsi":            mmsi,
                    "imo":             imo,
                    "callsign":        callsign,
                    "ship_type":       category,
                    "ship_type_code":  type_code,
                    "destination":     dest,
                    "eta":             eta_str,
                    "draught":         draught,
                    "length":          length if length else None,
                    "width":           width if width else None,
                    "sog_kts":         round(float(sog), 2) if sog is not None else None,
                    "cog":             round(float(cog), 1) if cog is not None else None,
                    "heading":         heading,
                    "flag_country":    None,
                    "trail":           trail,
                    "is_demo":         is_demo,
                },
            })

        breakdown = ", ".join(
            f"{n} {cat}" for cat, n in sorted(type_counts.items(), key=lambda x: -x[1])
        )
        logger.info(
            "[aisstream] Normalised %d vessels (%s) — %d skipped",
            len(events), breakdown or "none", skipped,
        )
        return events

    # ── Demo helpers ─────────────────────────────────────────────────────────

    def _get_demo_vessels(self) -> dict[int, dict]:
        now = time.monotonic()
        if self._demo_positions is None:
            self._demo_positions = {}
            for row in _DEMO_VESSELS:
                mmsi, name, lat, lng, hdg, sog, atype, dest = row
                self._demo_positions[mmsi] = {
                    "mmsi":        mmsi,
                    "name":        name,
                    "lat":         float(lat),
                    "lng":         float(lng),
                    "heading":     float(hdg),
                    "cog":         float(hdg),
                    "sog":         float(sog),
                    "type_code":   atype,
                    "destination": dest,
                    "_demo":       True,
                }
            self._demo_last_updated = now
            logger.info("[aisstream] Demo: initialised %d vessels", len(self._demo_positions))
        else:
            elapsed = now - self._demo_last_updated
            if elapsed > 0:
                for v in self._demo_positions.values():
                    if v.get("sog", 0) > 0.3:
                        new_lat, new_lng = _advance_position(
                            v["lat"], v["lng"], v["heading"], v["sog"], elapsed
                        )
                        v["lat"] = new_lat
                        v["lng"] = new_lng
                self._demo_last_updated = now
        return dict(self._demo_positions)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _handle_message(self, msg: dict, vessels: dict[int, dict]) -> None:
        msg_type = msg.get("MessageType")
        meta     = msg.get("MetaData") or {}
        message  = msg.get("Message") or {}

        mmsi = meta.get("MMSI")
        if not mmsi:
            return
        try:
            mmsi = int(mmsi)
        except (TypeError, ValueError):
            return

        if mmsi not in vessels:
            vessels[mmsi] = {"mmsi": mmsi}
            if mmsi in self._static:
                vessels[mmsi].update(self._static[mmsi])

        v = vessels[mmsi]

        if msg_type == "PositionReport":
            pr  = message.get("PositionReport") or {}
            lat = pr.get("Latitude") if pr.get("Latitude") is not None else meta.get("latitude")
            lng = pr.get("Longitude") if pr.get("Longitude") is not None else meta.get("longitude")
            if lat is not None:
                v["lat"]     = lat
                v["lng"]     = lng
                v["sog"]     = pr.get("Sog")
                v["cog"]     = pr.get("Cog")
                v["heading"] = pr.get("TrueHeading")
            ship_name = meta.get("ShipName", "").strip()
            if ship_name and not v.get("name"):
                v["name"] = ship_name

        elif msg_type == "ShipStaticData":
            sd = message.get("ShipStaticData") or {}
            static = {
                "name":        (sd.get("Name") or meta.get("ShipName", "")).strip() or None,
                "type_code":   sd.get("Type"),
                "imo":         sd.get("ImoNumber"),
                "callsign":    (sd.get("CallSign") or "").strip() or None,
                "destination": (sd.get("Destination") or "").strip() or None,
                "eta":         sd.get("Eta"),
                "draught":     sd.get("MaximumStaticDraught"),
                "dim":         sd.get("Dimension"),
            }
            v.update({k: val for k, val in static.items() if val is not None})
            self._static[mmsi] = {k: val for k, val in static.items() if val is not None}
