"""REST API routes — Story 1.3 / 2.9 / 3.4 / 3.5.

Endpoints:
  GET /api/health              — DB + Redis status, uptime
  GET /api/events              — paginated events with full filter set
  GET /api/events/{id}         — single event with full metadata
  GET /api/events/history      — nearest snapshot to a given timestamp
  GET /api/events/history/range — snapshot summaries over a time range
  GET /api/layers              — layer catalogue with live event counts
  GET /api/services            — ingestion service status (Story 2.9)
  GET /api/traffic/config      — traffic tile provider + config (Story 3.4)
  GET /api/ai/status           — AI analyzer status (Story 2.8)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2 import functions as geo_func
from geoalchemy2.types import Geometry as GeoGeometry
from sqlalchemy import cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.redis import redis_ping
from app.models.event import Event
from app.models.schemas import GlobeEventResponse, LayerInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# ── Static layer catalogue (counts filled at runtime from DB) ─────────────────
_LAYER_META: dict[str, dict] = {
    "flight":    {"label": "Flights",    "color": "#ffee00", "source": "OpenSky Network"},
    "news":      {"label": "News",       "color": "#00f0ff", "source": "GDELT"},
    "ship":      {"label": "Ships",      "color": "#00ff88", "source": "AISHub"},
    "satellite": {"label": "Satellites", "color": "#ff00aa", "source": "CelesTrak"},
    "disaster":  {"label": "Disasters",  "color": "#ff6600", "source": "EONET / USGS"},
    "conflict":  {"label": "Conflicts",  "color": "#ff0044", "source": "ACLED"},
    "traffic":   {"label": "Traffic",    "color": "#aa44ff", "source": "TomTom"},
    "camera":    {"label": "Cameras",    "color": "#888888", "source": "Public feeds"},
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _select_events_with_coords():
    """
    SELECT Event rows alongside extracted lat / lng from the PostGIS geography.

    We cast the geography column to geometry so that ST_X / ST_Y can extract
    individual ordinates without requiring Shapely as a Python dependency.
    """
    geom = cast(Event.location, GeoGeometry)
    return select(
        Event,
        geo_func.ST_Y(geom).label("lat"),
        geo_func.ST_X(geom).label("lng"),
    )


def _row_to_response(row) -> GlobeEventResponse:
    """Convert a mapping row (Event + lat + lng) into GlobeEventResponse."""
    ev: Event = row.Event
    return GlobeEventResponse(
        id=ev.id,
        event_type=ev.event_type,
        category=ev.category,
        title=ev.title,
        description=ev.description,
        latitude=float(row.lat) if row.lat is not None else 0.0,
        longitude=float(row.lng) if row.lng is not None else 0.0,
        altitude_m=ev.altitude_m,
        heading_deg=ev.heading_deg,
        speed_kmh=ev.speed_kmh,
        severity=ev.severity,
        source=ev.source,
        source_url=ev.source_url,
        source_id=ev.source_id,
        metadata=ev.metadata_,
        trail=ev.trail,
        created_at=ev.created_at,
        updated_at=ev.updated_at,
        expires_at=ev.expires_at,
    )


# ── /api/health ───────────────────────────────────────────────────────────────

@router.get("/health")
async def health_check(db: Annotated[AsyncSession, Depends(get_db)]):
    """Health check — DB + Redis connectivity and service uptime."""
    from app.main import APP_START_TIME  # avoid circular import at module level

    db_ok, db_detail = False, "unknown"
    try:
        await db.execute(text("SELECT 1"))
        db_ok, db_detail = True, "connected"
    except Exception as exc:
        db_detail = str(exc)
        logger.warning("Health check DB error: %s", exc)

    redis_ok = await redis_ping()
    uptime = round(time.time() - APP_START_TIME, 1) if APP_START_TIME else 0.0

    from app.scheduler import get_scheduler  # local import avoids circular dep
    sched = get_scheduler()
    scheduler_info = {
        "running": sched is not None and sched.running,
        "job_count": len(sched.get_jobs()) if sched and sched.running else 0,
    }

    return {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "service": "nexus-globe-backend",
        "db": db_detail,
        "redis": "connected" if redis_ok else "unavailable",
        "scheduler": scheduler_info,
        "uptime_seconds": uptime,
    }


# ── /api/layers ───────────────────────────────────────────────────────────────

@router.get("/layers", response_model=list[LayerInfo])
async def list_layers(db: Annotated[AsyncSession, Depends(get_db)]):
    """
    Return the layer catalogue with live event counts and last-updated timestamps.

    Each entry: type, label, color, source, status, event_count, last_updated
    """
    agg = await db.execute(
        select(
            Event.event_type,
            func.count(Event.id).label("cnt"),
            func.max(Event.created_at).label("last_updated"),
        ).group_by(Event.event_type)
    )
    db_stats: dict[str, dict] = {
        row.event_type: {"count": row.cnt, "last_updated": row.last_updated}
        for row in agg
    }

    return [
        LayerInfo(
            type=event_type,
            label=meta["label"],
            color=meta["color"],
            source=meta["source"],
            status="active" if event_type in db_stats else "coming_soon",
            event_count=db_stats.get(event_type, {}).get("count", 0),
            last_updated=db_stats.get(event_type, {}).get("last_updated"),
        )
        for event_type, meta in _LAYER_META.items()
    ]


# ── /api/events ───────────────────────────────────────────────────────────────

@router.get("/events", response_model=list[GlobeEventResponse])
async def list_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    # Comma-separated event types, e.g. ?type=flight,news
    type: str | None = Query(
        default=None,
        description="Comma-separated event types, e.g. 'flight,news'",
    ),
    severity_min: int = Query(default=1, ge=1, le=5),
    severity_max: int = Query(default=5, ge=1, le=5),
    # Bounding box: sw_lat,sw_lng,ne_lat,ne_lng
    bbox: str | None = Query(
        default=None,
        description="sw_lat,sw_lng,ne_lat,ne_lng — PostGIS bounding box filter",
    ),
    # ISO-8601 datetime, e.g. 2024-01-01T00:00:00Z
    since: datetime | None = Query(
        default=None,
        description="Return events created at or after this UTC timestamp",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """
    List events with optional filtering.

    Filters:
    - ``type``          — comma-separated event types (flight, news, ship …)
    - ``severity_min``  / ``severity_max`` — 1–5 severity range
    - ``bbox``          — PostGIS bounding box: sw_lat,sw_lng,ne_lat,ne_lng
    - ``since``         — only events created on or after this timestamp
    - ``limit`` / ``offset`` — pagination
    """
    stmt = (
        _select_events_with_coords()
        .where(Event.severity >= severity_min, Event.severity <= severity_max)
        .order_by(Event.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    # ── type filter (comma-separated) ────────────────────────────────────────
    if type:
        types = [t.strip() for t in type.split(",") if t.strip()]
        if types:
            stmt = stmt.where(Event.event_type.in_(types))

    # ── since filter ─────────────────────────────────────────────────────────
    if since:
        stmt = stmt.where(Event.created_at >= since)

    # ── bbox filter (PostGIS ST_Within) ──────────────────────────────────────
    if bbox:
        parts = bbox.split(",")
        if len(parts) != 4:
            raise HTTPException(
                status_code=422,
                detail="bbox must be four comma-separated floats: sw_lat,sw_lng,ne_lat,ne_lng",
            )
        try:
            sw_lat, sw_lng, ne_lat, ne_lng = (float(p) for p in parts)
        except ValueError:
            raise HTTPException(status_code=422, detail="bbox values must be numeric")

        envelope = geo_func.ST_MakeEnvelope(sw_lng, sw_lat, ne_lng, ne_lat, 4326)
        stmt = stmt.where(
            geo_func.ST_Within(cast(Event.location, GeoGeometry), envelope)
        )

    result = await db.execute(stmt)
    return [_row_to_response(row) for row in result.mappings()]


# ── /api/events/history (must be BEFORE /{event_id} to avoid routing collision) ───

@router.get("/events/history")
async def events_history(
    timestamp: datetime = Query(
        description="ISO-8601 UTC timestamp — returns the nearest snapshot to this time",
    ),
):
    """
    Return the nearest event snapshot to *timestamp*.

    The snapshot contains compressed event summaries (id, type, lat, lng,
    severity, title) captured every 15 minutes.  Searches ±4 hours from
    the requested time; returns 404 if no snapshot is found in that window.

    Story 3.5 — Event History & Snapshot Service.
    """
    from app.services.snapshot_service import get_snapshot_at

    result = await get_snapshot_at(timestamp)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No snapshot found within ±4 hours of {timestamp.isoformat()}",
        )
    return result


@router.get("/events/history/range")
async def events_history_range(
    start: datetime = Query(description="Range start (ISO-8601 UTC)"),
    end:   datetime = Query(description="Range end (ISO-8601 UTC)"),
    interval: int  = Query(
        default=1,
        ge=1,
        le=24,
        description="Bucket size in hours (1–24)",
    ),
):
    """
    Return snapshot summaries bucketed into *interval*-hour bins.

    Each bucket contains the event count and per-layer counts from the most
    recent snapshot in that bin.  Used by the Timeline scrubber (Story 3.11)
    to render event density over time.

    Story 3.5 — Event History & Snapshot Service.
    """
    from app.services.snapshot_service import get_history_range

    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")
    max_range = 7 * 24  # 7 days in hours
    range_hours = (end - start).total_seconds() / 3600
    if range_hours > max_range:
        raise HTTPException(
            status_code=422,
            detail=f"Range too large: maximum is {max_range}h (7 days)",
        )

    buckets = await get_history_range(start, end, interval_hours=interval)
    return {
        "start":      start.isoformat(),
        "end":        end.isoformat(),
        "interval_h": interval,
        "buckets":    buckets,
    }


# ── /api/events/{event_id} ────────────────────────────────────────────────────

@router.get("/events/{event_id}", response_model=GlobeEventResponse)
async def get_event(
    event_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return a single event by UUID with full metadata."""
    stmt = _select_events_with_coords().where(Event.id == event_id)
    result = await db.execute(stmt)
    row = result.mappings().first()

    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")

    return _row_to_response(row)


# ── /api/services ─────────────────────────────────────────────────────────────

@router.get("/services")
async def list_services():
    """
    Return the status and runtime stats of all registered ingestion services.

    Story 2.9 — scheduler status endpoint.
    """
    from app.scheduler import get_service_statuses, get_scheduler  # avoid circular
    statuses = get_service_statuses()

    # Enrich with scheduler job metadata (next run time, etc.)
    sched = get_scheduler()
    job_map: dict[str, object] = {}
    if sched and sched.running:
        for job in sched.get_jobs():
            job_map[job.id] = job

    enriched = []
    for svc in statuses:
        entry = dict(svc)
        job = job_map.get(f"ingest_{svc['name']}")
        entry["next_run"] = (
            job.next_run_time.isoformat() if job and getattr(job, "next_run_time", None) else None
        )
        enriched.append(entry)

    return {
        "services": enriched,
        "total": len(enriched),
        "scheduler_running": bool(sched and sched.running),
    }


# ── /api/traffic/config ──────────────────────────────────────────────────────

@router.get("/traffic/config")
async def traffic_config():
    """
    Return traffic layer configuration for the frontend.

    Tells the frontend:
    - whether traffic data is available (always true — demo fallback)
    - which tile provider is active (google / tomtom / demo)
    - the tile URL template for the overlay layer
    - the poll refresh interval

    Story 3.4 — Traffic Layer Integration.
    """
    from app.config import settings  # avoid circular at module level

    google_key: str = settings.google_maps_api_key or ""
    tomtom_key: str = getattr(settings, "tomtom_api_key", "") or ""

    if google_key:
        provider = "google"
        tile_url = (
            f"https://mt{{s}}.google.com/vt?lyrs=h,traffic"
            f"&x={{x}}&y={{y}}&z={{z}}&key={google_key}"
        )
    elif tomtom_key:
        provider = "tomtom"
        # TomTom raster traffic flow tiles
        tile_url = (
            f"https://{{s}}.api.tomtom.com/traffic/map/4/tile/flow/relative-delay/"
            f"{{z}}/{{x}}/{{y}}.png?key={tomtom_key}&tileSize=256"
        )
    else:
        provider = "demo"
        tile_url = None  # frontend falls back to coloured city dots only

    return {
        "enabled": True,
        "provider": provider,
        "tile_url": tile_url,
        "api_key_present": bool(google_key or tomtom_key),
        "refresh_interval_s": 120,
        "city_count": 20,
    }


# ── /api/ai/status ────────────────────────────────────────────────────────────

@router.get("/ai/status")
async def ai_status():
    """
    Return the AI analyzer status: enabled, model, daily counters, avg latency.

    Story 2.8 — AI analyzer status endpoint.
    """
    from app.services.ai_analyzer import get_analyzer  # avoid circular
    analyzer = get_analyzer()
    return analyzer.get_status()

