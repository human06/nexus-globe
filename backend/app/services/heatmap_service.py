"""Heatmap Data Aggregation Service (Story 3.6).

Aggregates live events into an H3 hexagonal grid for heatmap visualisation.

Usage:
    data = await get_heatmap(resolution=4, types=["news", "conflict"], hours=24)

Returns a dict compatible with /api/heatmap response schema:
    {
        "resolution": 4,
        "hexagons": [
            {
                "h3_index": "842a100ffffffff",
                "lat": 51.5,
                "lng": -0.1,
                "count": 23,
                "max_severity": 5,
                "types": {"news": 15, "conflict": 8}
            },
            ...
        ]
    }

Results are cached in Redis with a 60-second TTL.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import h3
from sqlalchemy import select
from sqlalchemy import func

from app.db.database import get_db_session
from app.models.event import Event

logger = logging.getLogger(__name__)

# Minimum H3 resolution (2 = continent, 6 = city block)
_MIN_RES = 2
_MAX_RES = 6

# Cache TTL in seconds
_CACHE_TTL = 60

# Time-window labels → hours
_TIME_WINDOWS: dict[str, int] = {
    "1h":  1,
    "6h":  6,
    "12h": 12,
    "24h": 24,
    "48h": 48,
    "7d":  168,
}


def _cache_key(resolution: int, types: list[str], hours: int) -> str:
    types_str = ",".join(sorted(types)) if types else "all"
    return f"heatmap:{resolution}:{types_str}:{hours}h"


async def get_heatmap(
    resolution: int = 4,
    types: list[str] | None = None,
    time_window: str = "24h",
) -> dict[str, Any]:
    """
    Compute (or return cached) H3 heatmap for the given parameters.

    Args:
        resolution: H3 resolution 2–6 (coarser→finer).
        types: List of event_type values to include. None = all types.
        time_window: One of "1h", "6h", "12h", "24h", "48h", "7d".

    Returns:
        dict with "resolution" and "hexagons" list.
    """
    resolution = max(_MIN_RES, min(_MAX_RES, resolution))
    hours = _TIME_WINDOWS.get(time_window, 24)

    # Try Redis cache first
    try:
        from app.db.redis import get_redis
        client = get_redis()
        key = _cache_key(resolution, types or [], hours)
        cached = await client.get(key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass  # cache miss or Redis unavailable — recompute

    result = await _compute_heatmap(resolution, types, hours)

    # Cache the result
    try:
        from app.db.redis import get_redis
        client = get_redis()
        await client.setex(key, _CACHE_TTL, json.dumps(result))
    except Exception:
        pass

    return result


async def _compute_heatmap(
    resolution: int,
    types: list[str] | None,
    hours: int,
) -> dict[str, Any]:
    """Query DB and aggregate events into H3 hexagons."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with get_db_session() as db:
        stmt = select(
            Event.event_type,
            Event.severity,
            func.ST_Y(
                func.ST_GeomFromWKB(func.ST_AsBinary(Event.location))
            ).label("lat"),
            func.ST_X(
                func.ST_GeomFromWKB(func.ST_AsBinary(Event.location))
            ).label("lng"),
        ).where(
            Event.created_at >= since,
            Event.location.isnot(None),
        )

        if types:
            stmt = stmt.where(Event.event_type.in_(types))

        result = await db.execute(stmt)
        rows = result.all()

    # Aggregate into H3 hex buckets
    hex_buckets: dict[str, dict] = {}

    for row in rows:
        if row.lat is None or row.lng is None:
            continue
        try:
            h3_idx = h3.geo_to_h3(float(row.lat), float(row.lng), resolution)
        except Exception:
            continue

        if h3_idx not in hex_buckets:
            center_lat, center_lng = h3.h3_to_geo(h3_idx)
            hex_buckets[h3_idx] = {
                "h3_index":    h3_idx,
                "lat":         round(center_lat, 4),
                "lng":         round(center_lng, 4),
                "count":       0,
                "max_severity": 0,
                "types":       {},
            }

        bucket = hex_buckets[h3_idx]
        bucket["count"] += 1
        bucket["max_severity"] = max(bucket["max_severity"], int(row.severity))
        t = row.event_type
        bucket["types"][t] = bucket["types"].get(t, 0) + 1

    # Sort by count descending for frontend convenience
    hexagons = sorted(hex_buckets.values(), key=lambda x: x["count"], reverse=True)

    logger.info(
        "[heatmap] res=%d types=%s time=%dh → %d hexagons from %d events",
        resolution,
        types or "all",
        hours,
        len(hexagons),
        len(rows),
    )

    return {
        "resolution": resolution,
        "time_window": f"{hours}h",
        "event_count": len(rows),
        "hexagons": hexagons,
    }
