"""NASA EONET Natural Disaster Ingestion — Story 2.5.

Polls the NASA EONET v3 REST API every 300 s for openly active natural
disaster events: wildfires, volcanic eruptions, severe storms, and floods.

API reference: https://eonet.gsfc.nasa.gov/docs/v3

Each EONET event has one or more *geometries* (time-stamped coordinate
observations).  For single-point events (volcanoes, wildfires) we use the
most-recent observation as the primary lat/lng.  For multi-point events
(storm tracks) we also populate ``metadata.trail`` so the frontend can draw
the full path.

Severity mapping:
  volcanic_eruption / severe_storm  →  4
  wildfire / flood / landslide       →  3
  drought / ice / snow / other       →  2

Events expire 7 days after their most-recent geometry timestamp.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)

_EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=50"

# EONET category title → internal category label
_CATEGORY_MAP: dict[str, str] = {
    "Wildfires":           "wildfire",
    "Volcanoes":           "volcanic_eruption",
    "Severe Storms":       "severe_storm",
    "Floods":              "flood",
    "Drought":             "drought",
    "Sea and Lake Ice":    "ice",
    "Earthquakes":         "earthquake",
    "Landslides":          "landslide",
    "Dust and Haze":       "haze",
    "Manmade":             "manmade",
    "Snow":                "snow",
    "Temperature Extremes":"temperature_extreme",
    "Water Color":         "water_color",
}

# Internal category → severity (1-5)
_SEVERITY_MAP: dict[str, int] = {
    "volcanic_eruption":  4,
    "severe_storm":       4,
    "wildfire":           3,
    "flood":              3,
    "landslide":          3,
    "earthquake":         3,
    "drought":            2,
    "ice":                2,
    "snow":               2,
    "temperature_extreme":2,
    "haze":               1,
    "manmade":            2,
    "water_color":        1,
}


def _parse_eonet_date(date_str: str | None) -> datetime | None:
    """Parse ISO 8601 date string from EONET geometry."""
    if not date_str:
        return None
    try:
        # EONET uses e.g. "2024-01-15T18:00:00Z"
        return datetime.fromisoformat(date_str.rstrip("Z")).replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


class EONETIngestionService(BaseIngestionService):
    """Natural disaster event feed from NASA EONET v3."""

    source_name = "eonet"
    poll_interval_seconds = 300

    # -----------------------------------------------------------------------
    # BaseIngestionService interface
    # -----------------------------------------------------------------------

    async def fetch_raw(self) -> dict[str, Any] | None:
        """Fetch open events from the EONET v3 API."""
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(_EONET_URL)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "[eonet] HTTP %s from EONET API: %s",
                exc.response.status_code, exc.request.url,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[eonet] fetch error: %s", exc)
            return None

        events = data.get("events", [])
        logger.info(
            "[eonet] API returned %d open events in %.1fs",
            len(events),
            time.monotonic() - t0,
        )
        return data

    async def normalize(self, raw: dict[str, Any] | None) -> list[dict]:
        """Convert EONET events to GlobeEvent dicts."""
        if not raw:
            return []

        api_events: list[dict] = raw.get("events", [])
        events: list[dict] = []
        skipped = 0
        cat_counts: dict[str, int] = {}

        for item in api_events:
            eonet_id = item.get("id", "")
            title    = item.get("title", "Unknown Event")
            link     = item.get("link", "")

            # Collect geometries (v3 uses "geometry" key, list of observations)
            geometries: list[dict] = item.get("geometry") or item.get("geometries") or []
            if not geometries:
                skipped += 1
                continue

            # Sort observations newest-first
            def _geom_dt(g: dict) -> datetime:
                return _parse_eonet_date(g.get("date")) or datetime.min.replace(tzinfo=timezone.utc)

            geometries_sorted = sorted(geometries, key=_geom_dt, reverse=True)
            latest_geom       = geometries_sorted[0]

            # Primary coordinate = most recent observation
            coords = latest_geom.get("coordinates")
            if not coords or len(coords) < 2:
                skipped += 1
                continue

            # GeoJSON is [lng, lat], EONET Point uses the same order
            lng = float(coords[0])
            lat = float(coords[1])

            # Most-recent observation timestamp
            last_dt = _parse_eonet_date(latest_geom.get("date")) or datetime.now(timezone.utc)

            # Category resolution
            categories: list[dict] = item.get("categories") or []
            raw_cat = (categories[0].get("title", "") if categories else "")
            category = _CATEGORY_MAP.get(raw_cat, "disaster")
            severity = _SEVERITY_MAP.get(category, 2)

            # EONET sources (e.g. InciWeb, MBGN)
            sources = [s.get("id", "") for s in (item.get("sources") or [])]

            # Build trail for multi-point events (storm tracks, eruption clouds)
            trail: list[dict] = []
            if len(geometries_sorted) > 1:
                for g in geometries_sorted:
                    gc = g.get("coordinates")
                    gd = _parse_eonet_date(g.get("date"))
                    if gc and len(gc) >= 2:
                        trail.append({
                            "lng":  float(gc[0]),
                            "lat":  float(gc[1]),
                            "date": gd.isoformat() if gd else None,
                        })

            # Accumulate category stats for log
            cat_label = raw_cat or "other"
            cat_counts[cat_label] = cat_counts.get(cat_label, 0) + 1

            # Description
            source_str = ", ".join(sources) if sources else "NASA EONET"
            description = (
                f"{title}. Category: {raw_cat or category}. "
                f"Last observed: {last_dt.strftime('%Y-%m-%d %H:%M UTC')}. "
                f"Source: {source_str}."
            )

            event: dict = {
                "event_type": "disaster",
                "category":   category,
                "title":      title[:200],
                "description":description,
                "latitude":   lat,
                "longitude":  lng,
                "severity":   severity,
                "source":     "eonet",
                "source_id":  eonet_id,
                "source_url": link,
                "expires_at": last_dt + timedelta(days=7),
                "needs_geocoding": False,
                "metadata": {
                    "eonet_id":        eonet_id,
                    "eonet_category":  raw_cat,
                    "sources":         sources,
                    "observation_count": len(geometries),
                    "last_observed":   last_dt.isoformat(),
                    **({"trail": trail} if trail else {}),
                },
            }
            events.append(event)

        # Build summary breakdown: "3 wildfires, 2 storms, 3 other"
        breakdown_parts = []
        for raw_cat_name, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
            label = _CATEGORY_MAP.get(raw_cat_name, "other")
            plural = label.replace("_", " ") + ("s" if cnt > 1 else "")
            breakdown_parts.append(f"{cnt} {plural}")

        breakdown_str = ", ".join(breakdown_parts) if breakdown_parts else "none"
        logger.info(
            "EONET: ingested %d events (%s) — %d skipped",
            len(events), breakdown_str, skipped,
        )
        return events
