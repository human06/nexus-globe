"""SGP4 Satellite Propagator — Story 3.1.

Fetches Two-Line Element (TLE) sets from CelesTrak, caches them for 6 hours,
and uses the skyfield library to propagate orbital positions + compute orbit
trail paths.

Usage
-----
    from app.services.satellite_propagator import propagator
    satellites = await propagator.get_all_positions()

The module exposes a single global ``propagator`` singleton so TLE data and
the skyfield timescale (which loads IERS data once) are shared across all
ingestion cycles.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TLE_CACHE_TTL_SECONDS = 6 * 3600          # Re-fetch TLEs after 6 hours
ORBIT_TRAIL_STEP_MINUTES  = 5             # One trail point every 5 min
ORBIT_TRAIL_DURATION_MIN  = 90            # 90 min ahead = one full orbit ≈
TRAIL_POINTS = ORBIT_TRAIL_DURATION_MIN // ORBIT_TRAIL_STEP_MINUTES   # 18

# CelesTrak group config: url_group → (max_count, severity, internal category)
SATELLITE_GROUPS: dict[str, tuple[str | None, int, str]] = {
    #  url_group      max_count  severity  category
    "stations":   (None,  3, "space_station"),
    "starlink":   ("100", 1, "communications_constellation"),
    "gps-ops":    (None,  1, "navigation"),
    "weather":    (None,  1, "weather_satellite"),
    "military":   (None,  2, "military_satellite"),
    "resource":   ("50",  1, "earth_observation"),
    "amateur":    ("30",  1, "amateur"),
}

CELESTRAK_BASE = "https://celestrak.org/NORAD/elements/gp.php"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SatellitePosition:
    """Fully-computed satellite state at the current instant."""
    norad_id: str
    name: str
    group: str
    category: str
    severity: int
    lat: float
    lng: float
    alt_km: float
    heading_deg: float
    speed_kmh: float
    period_min: float
    inclination_deg: float
    apogee_km: float
    perigee_km: float
    intl_designator: str
    epoch: str
    rcs_size: str
    object_type: str
    country_code: str
    launch_date: str
    trail: list[tuple[float, float]]   # [(lng, lat), …] of future positions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_heading(lat_deg: float, lng_deg: float,
                     vel_x: float, vel_y: float, vel_z: float) -> float:
    """Project TEME velocity vector onto the local East/North plane → heading in [0, 360)."""
    la = math.radians(lat_deg)
    lo = math.radians(lng_deg)
    sl, cl = math.sin(la), math.cos(la)
    slo, clo = math.sin(lo), math.cos(lo)
    # Unit north vector in GCRS
    n_x = -sl * clo
    n_y = -sl * slo
    n_z = cl
    # Unit east vector in GCRS
    e_x = -slo
    e_y = clo
    e_z = 0.0
    v_north = vel_x * n_x + vel_y * n_y + vel_z * n_z
    v_east  = vel_x * e_x + vel_y * e_y + vel_z * e_z
    return math.degrees(math.atan2(v_east, v_north)) % 360.0


def _orbital_speed_kmh(vel_x: float, vel_y: float, vel_z: float) -> float:
    """Return the magnitude of the velocity vector in km/h."""
    return math.sqrt(vel_x**2 + vel_y**2 + vel_z**2) * 3600.0


# ---------------------------------------------------------------------------
# Propagator
# ---------------------------------------------------------------------------

class SatellitePropagator:
    """
    Manages TLE caching + SGP4 propagation for all satellite groups.

    Call ``await propagator.get_all_positions()`` to get a freshly-computed
    list of ``SatellitePosition`` objects.  TLE data is re-fetched at most
    once every ``TLE_CACHE_TTL_SECONDS`` seconds; propagation itself is cheap
    and runs on every call.
    """

    def __init__(self) -> None:
        # group → list of skyfield EarthSatellite objects
        self._tle_cache: dict[str, list[Any]] = {}
        # group → list of raw TLE JSON dicts (for metadata)
        self._raw_cache: dict[str, list[dict]] = {}
        self._last_fetch: float = 0.0        # epoch seconds
        self._ts: Any = None                 # skyfield timescale (created lazily)
        self._lock = asyncio.Lock()

    def _get_timescale(self) -> Any:
        """Return (and lazily create) the skyfield timescale."""
        if self._ts is None:
            from skyfield.api import load
            # builtin=True avoids a Skyfield network request for leap-second data
            self._ts = load.timescale(builtin=True)
        return self._ts

    async def _fetch_group(self, client: httpx.AsyncClient,
                           group_key: str) -> tuple[list[Any], list[dict]]:
        """Fetch one CelesTrak group using TLE + GP JSON endpoints in parallel.

        Strategy:
        - Fetch TLE text format  (3 lines per satellite: name, line1, line2)
        - Fetch GP JSON format   (orbital parameters for metadata)
        Then pair them by NORAD catalog number for rich metadata.
        """
        from skyfield.api import EarthSatellite

        max_str, severity, category = SATELLITE_GROUPS[group_key]
        max_count = int(max_str) if max_str else None
        ts = self._get_timescale()

        tle_url  = f"{CELESTRAK_BASE}?GROUP={group_key}&FORMAT=tle"
        json_url = f"{CELESTRAK_BASE}?GROUP={group_key}&FORMAT=json"

        try:
            tle_resp, json_resp = await asyncio.gather(
                client.get(tle_url, timeout=30),
                client.get(json_url, timeout=30),
            )
            tle_resp.raise_for_status()
            json_resp.raise_for_status()
            tle_text: str = tle_resp.text
            gp_records: list[dict] = json_resp.json()
        except Exception as exc:
            logger.warning("[celestrak] Failed to fetch group %s: %s", group_key, exc)
            return [], []

        # Build NORAD → GP record lookup for metadata
        meta_by_norad: dict[str, dict] = {}
        for rec in gp_records:
            norad = str(rec.get("NORAD_CAT_ID", ""))
            if norad:
                meta_by_norad[norad] = rec

        # Parse 3-line TLE blocks
        lines = [ln.strip() for ln in tle_text.splitlines() if ln.strip()]
        sats: list[Any] = []
        raws: list[dict] = []
        count = 0
        i = 0
        while i < len(lines) - 2:
            name  = lines[i]
            line1 = lines[i + 1]
            line2 = lines[i + 2]
            # Validate TLE line prefixes
            if line1.startswith("1 ") and line2.startswith("2 "):
                if max_count and count >= max_count:
                    break
                try:
                    sat = EarthSatellite(line1, line2, name, ts)
                    # Extract NORAD from TLE line2 (columns 3-7)
                    norad = line2[2:7].strip()
                    meta = meta_by_norad.get(norad, {
                        "OBJECT_NAME": name,
                        "NORAD_CAT_ID": norad,
                    })
                    sats.append(sat)
                    raws.append(meta)
                    count += 1
                except Exception:
                    pass  # bad TLE — skip
                i += 3
            else:
                i += 1  # re-sync

        logger.debug("[celestrak] Fetched %d/%d sats from group %s",
                     count, len(lines) // 3, group_key)
        return sats, raws

    async def _refresh_tle_cache(self) -> None:
        """Fetch all TLE groups from CelesTrak and populate the cache."""
        logger.info("[celestrak] Refreshing TLE cache from CelesTrak …")
        start = time.monotonic()
        async with httpx.AsyncClient(follow_redirects=True) as client:
            tasks = {
                g: self._fetch_group(client, g)
                for g in SATELLITE_GROUPS
            }
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        new_tle: dict[str, list[Any]] = {}
        new_raw: dict[str, list[dict]] = {}
        for group_key, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning("[celestrak] Group %s raised: %s", group_key, result)
                new_tle[group_key] = self._tle_cache.get(group_key, [])
                new_raw[group_key] = self._raw_cache.get(group_key, [])
            else:
                sats, raws = result
                new_tle[group_key] = sats
                new_raw[group_key] = raws

        total = sum(len(v) for v in new_tle.values())
        elapsed = time.monotonic() - start
        self._tle_cache = new_tle
        self._raw_cache = new_raw
        self._last_fetch = time.monotonic()
        logger.info(
            "[celestrak] TLE cache refreshed — %d satellites across %d groups in %.1fs",
            total, len(new_tle), elapsed,
        )

    def _compute_trail(self, sat: Any, ts: Any) -> list[tuple[float, float]]:
        """Return a list of (lng, lat) for the next ORBIT_TRAIL_DURATION_MIN minutes."""
        t_now = ts.now()
        trail: list[tuple[float, float]] = []
        day_frac = ORBIT_TRAIL_STEP_MINUTES / (24.0 * 60.0)
        for i in range(TRAIL_POINTS):
            t = ts.tt_jd(t_now.tt + i * day_frac)
            try:
                geo = sat.at(t)
                sub = geo.subpoint()
                trail.append((sub.longitude.degrees, sub.latitude.degrees))
            except Exception:
                pass
        return trail

    def _propagate_one(self, sat: Any, raw: dict,
                       group_key: str, ts: Any) -> SatellitePosition | None:
        """Propagate a single satellite to the current time."""
        max_str, severity, category = SATELLITE_GROUPS[group_key]
        # ISS / space stations always get severity 3
        if category == "space_station":
            severity = 3
        try:
            t = ts.now()
            geo  = sat.at(t)
            sub  = geo.subpoint()
            pos  = geo.position.km     # (x, y, z) GCRS km
            vel  = geo.velocity.km_per_s  # (vx, vy, vz) GCRS km/s

            lat     = sub.latitude.degrees
            lng     = sub.longitude.degrees
            alt_km  = float(sub.elevation.km)

            if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
                return None
            if alt_km < 0 or alt_km > 60_000:
                return None   # bad propagation

            heading   = _compute_heading(lat, lng,
                                         float(vel[0]), float(vel[1]), float(vel[2]))
            speed_kmh = _orbital_speed_kmh(
                float(vel[0]), float(vel[1]), float(vel[2]))
        except Exception as exc:
            logger.debug("[celestrak] Propagation failed for %s: %s", sat.name, exc)
            return None

        # Metadata fields from CelesTrak JSON
        period_min    = float(raw.get("PERIOD", 0) or 0)
        inclination   = float(raw.get("INCLINATION", 0) or 0)
        apogee_km     = float(raw.get("APOAPSIS", 0) or 0)
        perigee_km    = float(raw.get("PERIAPSIS", 0) or 0)
        norad_id      = str(raw.get("NORAD_CAT_ID", ""))
        intl_design   = raw.get("INTLDES", "") or ""
        epoch         = raw.get("EPOCH", "") or ""
        rcs_size      = raw.get("RCS_SIZE", "") or ""
        object_type   = raw.get("OBJECT_TYPE", "") or ""
        country_code  = raw.get("COUNTRY_CODE", "") or ""
        launch_date   = raw.get("LAUNCH_DATE", "") or ""

        trail = self._compute_trail(sat, ts)

        return SatellitePosition(
            norad_id=norad_id,
            name=sat.name,
            group=group_key,
            category=category,
            severity=severity,
            lat=lat,
            lng=lng,
            alt_km=alt_km,
            heading_deg=heading,
            speed_kmh=speed_kmh,
            period_min=period_min,
            inclination_deg=inclination,
            apogee_km=apogee_km,
            perigee_km=perigee_km,
            intl_designator=intl_design,
            epoch=epoch,
            rcs_size=rcs_size,
            object_type=object_type,
            country_code=country_code,
            launch_date=launch_date,
            trail=trail,
        )

    async def get_all_positions(self) -> list[SatellitePosition]:
        """
        Return current positions for all cached satellites.
        Re-fetches TLEs if the cache has expired.
        """
        async with self._lock:
            age = time.monotonic() - self._last_fetch
            if age > TLE_CACHE_TTL_SECONDS or not self._tle_cache:
                await self._refresh_tle_cache()

        ts = self._get_timescale()
        start = time.monotonic()
        positions: list[SatellitePosition] = []
        group_counts: dict[str, int] = {}

        for group_key, sats in self._tle_cache.items():
            raws = self._raw_cache.get(group_key, [])
            g_count = 0
            for sat, raw in zip(sats, raws):
                pos = self._propagate_one(sat, raw, group_key, ts)
                if pos:
                    positions.append(pos)
                    g_count += 1
            group_counts[group_key] = g_count

        elapsed = time.monotonic() - start
        breakdown = ", ".join(f"{g}: {c}" for g, c in group_counts.items())
        logger.info(
            "[celestrak] Propagated %d satellites in %.2fs (%s)",
            len(positions), elapsed, breakdown,
        )
        return positions


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

propagator = SatellitePropagator()
