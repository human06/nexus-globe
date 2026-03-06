"""REST API routes."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.event import Event
from app.models.schemas import GlobeEventResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "nexus-globe-backend"}


@router.get("/layers")
async def list_layers():
    """Return available data layers and their status."""
    layers = [
        {"type": "news", "label": "News", "active": True},
        {"type": "flights", "label": "Flights", "active": True},
        {"type": "ships", "label": "Ships", "active": True},
        {"type": "satellites", "label": "Satellites", "active": True},
        {"type": "disasters", "label": "Disasters", "active": True},
        {"type": "conflicts", "label": "Conflicts", "active": True},
        {"type": "traffic", "label": "Traffic", "active": True},
        {"type": "cameras", "label": "Cameras", "active": True},
    ]
    return {"layers": layers}


@router.get("/events", response_model=list[GlobeEventResponse])
async def list_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    event_type: str | None = Query(default=None),
    severity_min: int = Query(default=1, ge=1, le=5),
    severity_max: int = Query(default=5, ge=1, le=5),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0),
):
    """
    List events with optional filters.

    Query params:
    - event_type: filter by type (news, flight, ship, …)
    - severity_min / severity_max: filter by severity range
    - bbox: minLat,minLng,maxLat,maxLng  (TODO: PostGIS spatial filter)
    - limit / offset: pagination
    """
    stmt = (
        select(Event)
        .where(Event.severity >= severity_min, Event.severity <= severity_max)
        .order_by(Event.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    # TODO: map PostGIS location back to lat/lng fields
    return [
        GlobeEventResponse(
            id=r.id,
            event_type=r.event_type,
            category=r.category,
            title=r.title,
            description=r.description,
            latitude=0.0,   # TODO: extract from r.location
            longitude=0.0,  # TODO: extract from r.location
            altitude_m=r.altitude_m,
            heading_deg=r.heading_deg,
            speed_kmh=r.speed_kmh,
            severity=r.severity,
            source=r.source,
            source_url=r.source_url,
            source_id=r.source_id,
            metadata=r.metadata_,
            trail=r.trail,
            created_at=r.created_at,
            updated_at=r.updated_at,
            expires_at=r.expires_at,
        )
        for r in rows
    ]


@router.get("/events/{event_id}", response_model=GlobeEventResponse)
async def get_event(
    event_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return a single event by ID."""
    result = await db.execute(select(Event).where(Event.id == event_id))
    row = result.scalar_one_or_none()
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Event not found")

    return GlobeEventResponse(
        id=row.id,
        event_type=row.event_type,
        category=row.category,
        title=row.title,
        description=row.description,
        latitude=0.0,
        longitude=0.0,
        altitude_m=row.altitude_m,
        heading_deg=row.heading_deg,
        speed_kmh=row.speed_kmh,
        severity=row.severity,
        source=row.source,
        source_url=row.source_url,
        source_id=row.source_id,
        metadata=row.metadata_,
        trail=row.trail,
        created_at=row.created_at,
        updated_at=row.updated_at,
        expires_at=row.expires_at,
    )
