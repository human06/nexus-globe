"""USGS Earthquake Ingestion — Story 2.4.

Polls two GeoJSON feeds from the USGS Earthquake Hazards Program every 60 s:

  all_hour       — every earthquake in the past hour (updated every minute)
  significant_day — significant earthquakes in the past day (M4.5+)

Both feeds are free, unauthenticated, and served as GeoJSON FeatureCollections.

Severity mapping (Richter / moment magnitude):
  M < 3.0    →  1  (micro / minor, rarely felt)
  3.0 – 4.4  →  2  (light, felt but little damage)
  4.5 – 5.4  →  3  (moderate, some damage possible)
  5.5 – 6.9  →  4  (strong, major damage in populated areas)
  M >= 7.0   →  5  (major / great, catastrophic)

Events expire after 7 days in line with USGS's own feed retention window.
Same-ID deduplication is handled by the base upsert pipeline
(ON CONFLICT source, source_id DO UPDATE).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)

_ALL_HOUR_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
)
_SIG_DAY_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_day.geojson"
)


def _mag_to_severity(mag: float | None) -> int:
    if mag is None:
        return 1
    if mag >= 7.0:
        return 5
    if mag >= 5.5:
        return 4
    if mag >= 4.5:
        return 3
    if mag >= 3.0:
        return 2
    return 1


class USGSIngestionService(BaseIngestionService):
    """Real-time earthquake feed from the USGS Earthquake Hazards Program."""

    source_name = "usgs"
    poll_interval_seconds = 60

    # -----------------------------------------------------------------------
    # BaseIngestionService interface
    # -----------------------------------------------------------------------

    async def fetch_raw(self) -> dict[str, Any] | None:
        """
        Fetch all_hour + significant_day feeds concurrently.

        Returns ``{"features": [<geojson_feature>, ...]}`` with features
        from both feeds merged and deduplicated by USGS event ID.
        """
        t0 = time.monotonic()

        async with httpx.AsyncClient(timeout=15.0) as client:
            hour_task = asyncio.create_task(self._fetch_feed(client, _ALL_HOUR_URL))
            sig_task  = asyncio.create_task(self._fetch_feed(client, _SIG_DAY_URL))
            hour_result, sig_result = await asyncio.gather(
                hour_task, sig_task, return_exceptions=True
            )

        hour_features: list = []
        sig_features:  list = []

        if isinstance(hour_result, Exception):
            logger.warning("[usgs] all_hour feed failed: %s", hour_result)
        else:
            hour_features = (hour_result or {}).get("features", [])

        if isinstance(sig_result, Exception):
            logger.warning("[usgs] significant_day feed failed: %s", sig_result)
        else:
            sig_features = (sig_result or {}).get("features", [])

        if not hour_features and not sig_features:
            logger.warning("[usgs] Both feeds returned no data")
            return None

        # Merge, dedup by USGS event ID (significant_day may overlap with all_hour)
        seen_ids: set[str] = set()
        merged: list = []
        for feat in hour_features + sig_features:
            eid = feat.get("id", "")
            if eid and eid not in seen_ids:
                seen_ids.add(eid)
                merged.append(feat)

        logger.info(
            "[usgs] Fetched %d earthquakes (%d hour, %d significant) in %.1fs",
            len(merged), len(hour_features), len(sig_features),
            time.monotonic() - t0,
        )
        return {"features": merged}

    async def _fetch_feed(self, client: httpx.AsyncClient, url: str) -> dict:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()

    async def normalize(self, raw: dict[str, Any] | None) -> list[dict]:
        """Convert USGS GeoJSON features → GlobeEvent dicts."""
        if not raw:
            return []

        features = raw.get("features", [])
        events: list[dict] = []
        skipped = 0

        for feat in features:
            props  = feat.get("properties") or {}
            geom   = feat.get("geometry")   or {}
            coords = geom.get("coordinates")  # [lng, lat, depth_km]
            usgs_id = feat.get("id", "")

            if not coords or len(coords) < 2 or not usgs_id:
                skipped += 1
                continue

            lng, lat = float(coords[0]), float(coords[1])
            depth_km = float(coords[2]) if len(coords) > 2 else None

            mag      = props.get("mag")
            mag_type = props.get("magType", "")
            place    = props.get("place", "Unknown location")
            status   = props.get("status", "")
            alert    = props.get("alert")       # "green" | "yellow" | "orange" | "red"
            tsunami  = props.get("tsunami", 0)
            felt     = props.get("felt")        # number of felt reports
            cdi      = props.get("cdi")         # community internet intensity (0-10)
            mmi      = props.get("mmi")         # modified mercalli intensity (0-10)
            time_ms  = props.get("time")        # epoch ms
            url_link = props.get("url", "")

            # Timestamp
            if time_ms:
                published = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc)
            else:
                published = datetime.now(timezone.utc)

            # Title per spec: "M{mag} Earthquake — {place}"
            mag_str = f"{mag:.1f}" if mag is not None else "?"
            title = f"M{mag_str} Earthquake \u2014 {place}"

            severity = _mag_to_severity(mag)

            events.append({
                "event_type":  "disaster",
                "category":    "earthquake",
                "title":       title[:200],
                "description": (
                    f"Magnitude {mag_str} {mag_type} earthquake {place}. "
                    f"Depth: {depth_km:.1f} km." if depth_km else
                    f"Magnitude {mag_str} {mag_type} earthquake {place}."
                ),
                "latitude":    lat,
                "longitude":   lng,
                "severity":    severity,
                "source":      "usgs",
                "source_id":   usgs_id,
                "source_url":  url_link,
                "expires_at":  published + timedelta(days=7),
                "metadata": {
                    "magnitude":    mag,
                    "mag_type":     mag_type,
                    "depth_km":     depth_km,
                    "felt_reports": felt,
                    "tsunami_flag": bool(tsunami),
                    "alert_level":  alert,
                    "mmi":          mmi,
                    "cdi":          cdi,
                    "status":       status,
                    "place":        place,
                    "published_date": published.isoformat(),
                },
            })

        # Log summary
        sig_count = sum(1 for e in events if e["severity"] >= 4)
        logger.info(
            "USGS: ingested %d earthquakes (%d significant M5.5+) — %d skipped",
            len(events), sig_count, skipped,
        )
        return events
