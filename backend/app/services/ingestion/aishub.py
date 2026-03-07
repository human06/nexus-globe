"""AISHub Ship Tracking Ingestion — Story 2.6.

Polls AISHub every 60 s for live AIS vessel positions worldwide.

Requires ``AISHUB_API_KEY`` (username) — gracefully skips if absent.
Free accounts provide a rotating ~few-hundred-vessel snapshot; paid tiers
give full global coverage.

API URL: https://data.aishub.net/ws.php?username=<key>&format=1&output=json&compress=0

Response structure:
  [
    {"ERROR": false, "USERNAME": "...", "FORMAT": 1, "RECORDS": N},
    [ <vessel_dict>, ... ]
  ]

Ship type mapping (AIS Type-of-Ship & Cargo code table):
  30-39  → fishing
  50-59  → special     (pilotage, tug, port, etc.)
  60-69  → passenger
  70-79  → cargo
  80-89  → tanker

Trail: up to 20 most-recent positions are accumulated in-memory across
poll cycles so the frontend can draw track lines.

Events expire 120 s after ingestion — ships not seen for two full cycles
become stale and are TTL-evicted from Redis.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)

_AISHUB_BASE = "https://data.aishub.net/ws.php"
_TRAIL_MAXLEN = 20
_MIN_SPEED_KTS = 0.5  # filter stationary vessels below this threshold

# AIS ship type code range → category label
_SHIP_TYPES: list[tuple[range, str]] = [
    (range(30, 40), "fishing"),
    (range(50, 60), "special"),
    (range(60, 70), "passenger"),
    (range(70, 80), "cargo"),
    (range(80, 90), "tanker"),
]


def _classify_ship(type_code: int | None) -> str:
    """Map AIS type code → internal category string."""
    if type_code is None:
        return "ship"
    for rng, label in _SHIP_TYPES:
        if type_code in rng:
            return label
    return "ship"


class AISHubIngestionService(BaseIngestionService):
    """Live vessel tracking via AISHub AIS data feed."""

    source_name = "aishub"
    poll_interval_seconds = 60

    def __init__(self) -> None:
        super().__init__()
        # MMSI → deque of up to _TRAIL_MAXLEN {lat, lng, ts} dicts
        self._position_history: dict[int, deque] = {}

    # -----------------------------------------------------------------------
    # BaseIngestionService interface
    # -----------------------------------------------------------------------

    async def fetch_raw(self) -> list | None:
        """Fetch vessel snapshot from AISHub.  Returns None if no API key."""
        from app.config import settings

        api_key = settings.aishub_api_key
        if not api_key:
            logger.debug("[aishub] AISHUB_API_KEY not configured — skipping")
            return None

        t0 = time.monotonic()
        url = (
            f"{_AISHUB_BASE}"
            f"?username={api_key}&format=1&output=json&compress=0"
        )
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "[aishub] HTTP %s: %s", exc.response.status_code, exc.request.url
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[aishub] fetch error: %s", exc)
            return None

        # AISHub returns [meta_dict, [vessel, ...]] or error list
        if not isinstance(data, list) or len(data) < 2:
            logger.warning("[aishub] Unexpected response shape")
            return None

        meta, vessels = data[0], data[1]
        if isinstance(meta, dict) and meta.get("ERROR"):
            logger.warning("[aishub] API error: %s", meta)
            return None

        vessel_list = vessels if isinstance(vessels, list) else []
        logger.info(
            "[aishub] API returned %d vessels in %.1fs",
            len(vessel_list),
            time.monotonic() - t0,
        )
        return vessel_list

    async def normalize(self, raw: list | None) -> list[dict]:
        """Convert AISHub vessel list → GlobeEvent dicts."""
        if not raw:
            return []

        events: list[dict] = []
        skipped_stationary = 0
        skipped_nocoord = 0
        seen_mmsi: set[int] = set()
        type_counts: dict[str, int] = {}
        now = datetime.now(timezone.utc)

        for vessel in raw:
            if not isinstance(vessel, dict):
                continue

            mmsi = vessel.get("MMSI") or vessel.get("MMSI_STRING")
            try:
                mmsi = int(mmsi)
            except (TypeError, ValueError):
                continue

            # Dedup by MMSI within this batch
            if mmsi in seen_mmsi:
                continue
            seen_mmsi.add(mmsi)

            # Coordinates — AISHub omits 0/0 for unknown
            lat_raw = vessel.get("LATITUDE")
            lng_raw = vessel.get("LONGITUDE")
            try:
                lat = float(lat_raw)
                lng = float(lng_raw)
            except (TypeError, ValueError):
                skipped_nocoord += 1
                continue

            if lat == 0.0 and lng == 0.0:
                skipped_nocoord += 1
                continue

            # Filter stationary vessels
            sog = _safe_float(vessel.get("SOG") or vessel.get("SPEED"))
            if sog is not None and sog < _MIN_SPEED_KTS:
                skipped_stationary += 1
                continue

            # Ship classification
            ship_type_code = _safe_int(vessel.get("SHIPTYPE"))
            ship_category  = _classify_ship(ship_type_code)

            # Accumulate trail
            self._position_history.setdefault(mmsi, deque(maxlen=_TRAIL_MAXLEN))
            self._position_history[mmsi].appendleft({
                "lat": round(lat, 5),
                "lng": round(lng, 5),
                "ts":  now.isoformat(),
            })
            trail = list(self._position_history[mmsi])

            # Names and identifiers
            name          = str(vessel.get("NAME", "")).strip() or f"MMSI {mmsi}"
            imo           = _safe_int(vessel.get("IMO"))
            callsign      = str(vessel.get("CALLSIGN", "")).strip() or None
            destination   = str(vessel.get("DESTINATION", "")).strip() or None
            eta           = str(vessel.get("ETA", "")).strip() or None
            draught       = _safe_float(vessel.get("DRAUGHT"))
            length        = _safe_float(vessel.get("LENGTH"))
            width         = _safe_float(vessel.get("WIDTH"))
            cog           = _safe_float(vessel.get("COG") or vessel.get("COURSE"))
            heading       = _safe_int(vessel.get("HDG") or vessel.get("HEADING"))

            type_counts[ship_category] = type_counts.get(ship_category, 0) + 1

            # Title: "{name} ({ship_category})"
            title = f"{name} ({ship_category})"[:200]

            speed_str = f"{sog:.1f} kts" if sog is not None else "speed unknown"
            dest_str  = f" → {destination}" if destination else ""
            description = (
                f"{ship_category.title()} vessel {name}"
                f"{dest_str}. Speed: {speed_str}."
            )

            events.append({
                "event_type":    "ship",
                "category":      ship_category,
                "title":         title,
                "description":   description,
                "latitude":      round(lat, 5),
                "longitude":     round(lng, 5),
                "severity":      1,
                "source":        "aishub",
                "source_id":     str(mmsi),
                "source_url":    f"https://www.marinetraffic.com/en/ais/details/ships/mmsi:{mmsi}",
                "expires_at":    now + timedelta(seconds=120),
                "needs_geocoding": False,
                "metadata": {
                    "mmsi":         mmsi,
                    "imo":          imo,
                    "callsign":     callsign,
                    "ship_type":    ship_category,
                    "ship_type_code": ship_type_code,
                    "destination":  destination,
                    "eta":          eta,
                    "draught":      draught,
                    "length":       length,
                    "width":        width,
                    "sog_kts":      sog,
                    "cog":          cog,
                    "heading":      heading,
                    "flag_country": None,
                    "trail":        trail,
                },
            })

        # Log summary
        breakdown = ", ".join(
            f"{cnt} {cat}" for cat, cnt in sorted(type_counts.items(), key=lambda x: -x[1])
        )
        logger.info(
            "AISHub: ingested %d vessels (%s) — %d stationary / %d no-coord skipped",
            len(events), breakdown or "none",
            skipped_stationary, skipped_nocoord,
        )
        return events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
