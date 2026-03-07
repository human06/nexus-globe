"""Traffic Layer Ingestion — Story 3.4.

Polls real-time congestion data for the top 20 global cities every 120 seconds.

Provider priority:
  1. TomTom Traffic Flow API (free tier; requires TOMTOM_API_KEY)
     https://developer.tomtom.com/traffic-api/documentation/traffic-flow/flow-segment-data
  2. Demo / synthetic data based on realistic time-of-day rush-hour patterns
     (used when no API key is set, so the layer still renders on the globe)

Events produced:
  event_type:  "traffic"
  category:    "traffic_congestion" | "traffic_free" | "traffic_moderate"
  severity:    1–5 (1 = free flow, 5 = gridlock)
  source_id:   city_slug (e.g. "new_york")
  expires_at:  3 minutes (refreshed every 2-minute poll cycle)

The `/api/traffic/config` endpoint (routes.py) exposes tile URL + provider
metadata for the frontend to render its overlay tile layer.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)

# ── City catalogue ─────────────────────────────────────────────────────────────

TRAFFIC_CITIES = [
    {"name": "London",        "slug": "london",        "lat": 51.5074,  "lng": -0.1278},
    {"name": "New York",      "slug": "new_york",      "lat": 40.7128,  "lng": -74.0060},
    {"name": "Tokyo",         "slug": "tokyo",         "lat": 35.6762,  "lng": 139.6503},
    {"name": "Beijing",       "slug": "beijing",       "lat": 39.9042,  "lng": 116.4074},
    {"name": "Mumbai",        "slug": "mumbai",        "lat": 19.0760,  "lng": 72.8777},
    {"name": "São Paulo",     "slug": "sao_paulo",     "lat": -23.5505, "lng": -46.6333},
    {"name": "Cairo",         "slug": "cairo",         "lat": 30.0444,  "lng": 31.2357},
    {"name": "Lagos",         "slug": "lagos",         "lat": 6.5244,   "lng": 3.3792},
    {"name": "Mexico City",   "slug": "mexico_city",   "lat": 19.4326,  "lng": -99.1332},
    {"name": "Los Angeles",   "slug": "los_angeles",   "lat": 34.0522,  "lng": -118.2437},
    {"name": "Paris",         "slug": "paris",         "lat": 48.8566,  "lng": 2.3522},
    {"name": "Jakarta",       "slug": "jakarta",       "lat": -6.2088,  "lng": 106.8456},
    {"name": "Istanbul",      "slug": "istanbul",      "lat": 41.0082,  "lng": 28.9784},
    {"name": "Dhaka",         "slug": "dhaka",         "lat": 23.8103,  "lng": 90.4125},
    {"name": "Karachi",       "slug": "karachi",       "lat": 24.8607,  "lng": 67.0011},
    {"name": "Moscow",        "slug": "moscow",        "lat": 55.7558,  "lng": 37.6173},
    {"name": "Seoul",         "slug": "seoul",         "lat": 37.5665,  "lng": 126.9780},
    {"name": "Tehran",        "slug": "tehran",        "lat": 35.6892,  "lng": 51.3890},
    {"name": "Delhi",         "slug": "delhi",         "lat": 28.6139,  "lng": 77.2090},
    {"name": "Osaka",         "slug": "osaka",         "lat": 34.6937,  "lng": 135.5023},
]

TOMTOM_FLOW_URL = (
    "https://api.tomtom.com/traffic/services/4/flowSegmentData"
    "/absolute/10/json"
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _congestion_to_severity(congestion_pct: float) -> int:
    """Map congestion percentage (0–100) to severity 1–5."""
    if congestion_pct >= 70:
        return 5  # gridlock
    if congestion_pct >= 50:
        return 4  # heavy
    if congestion_pct >= 30:
        return 3  # moderate
    if congestion_pct >= 10:
        return 2  # light congestion
    return 1      # free flow


def _congestion_to_category(congestion_pct: float) -> str:
    if congestion_pct >= 50:
        return "traffic_congestion"
    if congestion_pct >= 20:
        return "traffic_moderate"
    return "traffic_free"


def _demo_congestion(city: dict, now: datetime) -> dict:
    """
    Produce time-realistic synthetic traffic for a city when no API key is set.

    Uses the city's local hour (approximated from longitude) and a rush-hour
    curve to generate plausible congestion percentages.
    """
    # Approximate local hour from longitude (UTC offset ≈ lng / 15)
    utc_offset_h = city["lng"] / 15.0
    local_hour = (now.hour + utc_offset_h) % 24

    # Rush-hour peaks: morning 7–9, evening 17–19
    def rush(h: float) -> float:
        """Gaussian-shaped rush hour contribution."""
        return math.exp(-0.5 * ((h - 8) / 1.2) ** 2) + math.exp(-0.5 * ((h - 18) / 1.2) ** 2)

    peak = rush(local_hour)  # 0..~1

    # Cities that are chronically congested (add a city-specific bias)
    _CHRONIC: dict[str, float] = {
        "mumbai": 0.30, "karachi": 0.25, "lagos": 0.25,
        "dhaka": 0.25,  "jakarta": 0.20, "cairo": 0.20,
        "mexico_city": 0.18, "tehran": 0.18,
    }
    chronic_bias = _CHRONIC.get(city["slug"], 0.05)

    congestion = min(100.0, (peak * 55.0 + chronic_bias * 100.0))
    free_flow_speed = 80.0  # km/h generic urban arterial
    avg_speed = max(5.0, free_flow_speed * (1 - congestion / 100))

    return {
        "current_speed_kmh": round(avg_speed, 1),
        "free_flow_speed_kmh": free_flow_speed,
        "congestion_pct": round(congestion, 1),
        "road_closure": False,
        "is_demo": True,
    }


# ── Main service ───────────────────────────────────────────────────────────────

class TrafficIngestionService(BaseIngestionService):
    """Ingests real-time city traffic congestion (TomTom or synthetic demo)."""

    source_name = "traffic"
    poll_interval_seconds = 120

    # ------------------------------------------------------------------ #
    # fetch_raw                                                            #
    # ------------------------------------------------------------------ #

    async def fetch_raw(self) -> Any:
        """
        Return a list of per-city traffic dicts.
        Uses TomTom if TOMTOM_API_KEY is set, otherwise synthetic demo data.
        """
        now = datetime.now(timezone.utc)

        tomtom_key: str = getattr(settings, "tomtom_api_key", "") or ""

        if tomtom_key:
            return await self._fetch_tomtom(tomtom_key, now)

        # No API key — fall through to demo data (always succeeds)
        logger.info(
            "[traffic] No TOMTOM_API_KEY set — using synthetic demo traffic data. "
            "Get a free key at https://developer.tomtom.com/"
        )
        return self._fetch_demo(now)

    async def _fetch_tomtom(self, api_key: str, now: datetime) -> list[dict]:
        """Query TomTom Traffic Flow API for each city concurrently."""
        results: list[dict] = []
        errors = 0

        async with httpx.AsyncClient(timeout=10.0) as client:
            for city in TRAFFIC_CITIES:
                params = {
                    "key": api_key,
                    "point": f"{city['lat']},{city['lng']}",
                    "unit": "KMPH",
                }
                try:
                    resp = await client.get(TOMTOM_FLOW_URL, params=params)
                    resp.raise_for_status()
                    data = resp.json().get("flowSegmentData", {})

                    current_speed = float(data.get("currentSpeed", 0) or 0)
                    free_flow     = float(data.get("freeFlowSpeed", 80) or 80)
                    if free_flow <= 0:
                        free_flow = 80.0

                    congestion = max(0.0, min(100.0, (1 - current_speed / free_flow) * 100))

                    results.append({
                        **city,
                        "current_speed_kmh": round(current_speed, 1),
                        "free_flow_speed_kmh": round(free_flow, 1),
                        "congestion_pct": round(congestion, 1),
                        "road_closure": bool(data.get("roadClosure", False)),
                        "confidence": float(data.get("confidence", 1.0)),
                        "is_demo": False,
                    })
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    logger.debug("[traffic] TomTom error for %s: %s", city["name"], exc)
                    # Fall back to synthetic for this city
                    demo = _demo_congestion(city, now)
                    results.append({**city, **demo, "is_demo": True})

        if errors:
            logger.warning("[traffic] TomTom: %d/%d cities used demo fallback", errors, len(TRAFFIC_CITIES))
        else:
            logger.info("[traffic] TomTom: fetched %d cities successfully", len(results))
        return results

    def _fetch_demo(self, now: datetime) -> list[dict]:
        """Generate synthetic traffic data for all cities (no API key required)."""
        return [
            {**city, **_demo_congestion(city, now)}
            for city in TRAFFIC_CITIES
        ]

    # ------------------------------------------------------------------ #
    # normalize                                                            #
    # ------------------------------------------------------------------ #

    async def normalize(self, raw: Any) -> list[dict]:
        """Convert per-city traffic dicts → GlobeEvent dicts."""
        if not raw:
            return []

        events: list[dict] = []
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=3)

        for item in raw:
            congestion = float(item.get("congestion_pct", 0))
            severity   = _congestion_to_severity(congestion)
            category   = _congestion_to_category(congestion)
            city_name  = item.get("name", "Unknown City")
            slug       = item.get("slug", city_name.lower().replace(" ", "_"))

            # Title reflects current conditions
            if congestion >= 70:
                condition = "gridlock"
            elif congestion >= 50:
                condition = "heavy traffic"
            elif congestion >= 30:
                condition = "moderate traffic"
            elif congestion >= 10:
                condition = "light traffic"
            else:
                condition = "free flow"

            current_speed = float(item.get("current_speed_kmh", 0))
            free_flow     = float(item.get("free_flow_speed_kmh", 80))

            title = f"{city_name} — {condition} ({current_speed:.0f} km/h)"

            events.append({
                "event_type":  "traffic",
                "category":    category,
                "title":       title,
                "description": (
                    f"{city_name}: {condition}. "
                    f"Current speed {current_speed:.0f} km/h vs "
                    f"free-flow {free_flow:.0f} km/h "
                    f"({congestion:.0f}% congestion)."
                ),
                "latitude":   float(item["lat"]),
                "longitude":  float(item["lng"]),
                "altitude_m": 0.0,
                "severity":   severity,
                "source":     "tomtom" if not item.get("is_demo") else "demo",
                "source_id":  slug,
                "expires_at": expires_at,
                "metadata": {
                    "city_name":             city_name,
                    "slug":                  slug,
                    "avg_speed_kmh":         current_speed,
                    "free_flow_speed_kmh":   free_flow,
                    "congestion_percent":    congestion,
                    "road_closure_count":    1 if item.get("road_closure") else 0,
                    "confidence":            float(item.get("confidence", 1.0)),
                    "is_demo":               bool(item.get("is_demo", False)),
                },
            })

        # Log summary
        avg_cong = sum(float(i.get("congestion_pct", 0)) for i in raw) / max(len(raw), 1)
        worst = max(raw, key=lambda i: float(i.get("congestion_pct", 0)), default={})
        logger.info(
            "[traffic] %d cities updated — avg congestion %.0f%%, worst: %s (%.0f%%)",
            len(events),
            avg_cong,
            worst.get("name", "?"),
            float(worst.get("congestion_pct", 0)),
        )
        return events
