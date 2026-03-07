"""CelesTrak Satellite TLE Ingestion — Story 3.1.

Fetches Two-Line Element (TLE) sets from CelesTrak and uses SGP4/skyfield
to calculate real-time orbital positions.  The ingestion cycle runs every
30 seconds (propagation interval); TLE data itself is refreshed at most
once every 6 hours because TLE sets change slowly.

Data sources
------------
- stations   — ISS, Tiangong, CSS  (severity 3)
- starlink   — sample of 100 (severity 1)
- gps-ops    — GPS constellation   (severity 1)
- weather    — NOAA / Meteosat     (severity 1)
- military   — US/allied mil-sats  (severity 2)
- resource   — Landsat, Sentinel …  (severity 1)
- amateur    — sample of 30        (severity 1)

Each GlobeEvent produced by this service carries a ``trail`` — the next
90 min of predicted positions (18 points × 5 min) so the frontend can
draw the orbital arc.

Events expire after 30 seconds so the frontend always sees fresh positions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.ingestion.base import BaseIngestionService
from app.services.satellite_propagator import SatellitePosition, propagator

logger = logging.getLogger(__name__)


class CelesTrakIngestionService(BaseIngestionService):
    """Propagates all cached TLE satellites and pushes them as GlobeEvents."""

    source_name          = "celestrak"
    poll_interval_seconds = 30          # position propagation frequency

    # ------------------------------------------------------------------ #
    # fetch_raw: delegate to the shared propagator singleton               #
    # ------------------------------------------------------------------ #

    async def fetch_raw(self) -> list[SatellitePosition] | None:
        try:
            positions = await propagator.get_all_positions()
            if not positions:
                logger.warning("[celestrak] Propagator returned no positions")
                return None
            return positions
        except Exception as exc:
            logger.exception("[celestrak] Propagation error: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    # normalize: convert SatellitePosition → GlobeEvent dict              #
    # ------------------------------------------------------------------ #

    async def normalize(self, raw: list[SatellitePosition]) -> list[dict]:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=60)   # generous TTL; scheduler refreshes every 30s

        events: list[dict] = []
        for pos in raw:
            period_str = f"{pos.period_min:.1f}min" if pos.period_min else "?"
            description = (
                f"{pos.name} — {pos.category} at {pos.alt_km:.0f} km, "
                f"period {period_str}"
            )
            # source_id = canonical NORAD catalogue number
            source_id = pos.norad_id or pos.name.replace(" ", "_")

            trail_dicts = [
                {"lng": lng, "lat": lat}
                for lng, lat in pos.trail
            ]

            events.append({
                "event_type":   "satellite",
                "category":     pos.category,
                "title":        pos.name,
                "description":  description,
                "latitude":     round(pos.lat, 4),
                "longitude":    round(pos.lng, 4),
                "altitude_m":   round(pos.alt_km * 1000, 0),
                "heading_deg":  round(pos.heading_deg, 1),
                "speed_kmh":    round(pos.speed_kmh, 1),
                "severity":     pos.severity,
                "source":       "celestrak",
                "source_id":    source_id,
                "source_url":   f"https://celestrak.org/NORAD/elements/gp.php?CATNR={pos.norad_id}",
                "trail":        trail_dicts,
                "expires_at":   expires_at,
                "metadata": {
                    "norad_id":        pos.norad_id,
                    "intl_designator": pos.intl_designator,
                    "epoch":           pos.epoch,
                    "inclination_deg": round(pos.inclination_deg, 2),
                    "period_min":      round(pos.period_min, 2),
                    "apogee_km":       round(pos.apogee_km, 1),
                    "perigee_km":      round(pos.perigee_km, 1),
                    "rcs_size":        pos.rcs_size,
                    "orbit_type":      pos.category,
                    "object_type":     pos.object_type,
                    "country_code":    pos.country_code,
                    "launch_date":     pos.launch_date,
                    "group":           pos.group,
                    "alt_km":          round(pos.alt_km, 1),
                },
            })

        # Group summary for the log
        from collections import Counter
        by_group = Counter(p.group for p in raw)
        breakdown = ", ".join(f"{g}: {c}" for g, c in sorted(by_group.items()))
        logger.info(
            "[celestrak] Normalised %d satellite events (%s)",
            len(events), breakdown,
        )
        return events
