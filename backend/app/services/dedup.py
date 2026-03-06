"""Event deduplication and PostgreSQL upsert logic."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from geoalchemy2.elements import WKTElement
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.database import AsyncSessionLocal
from app.models.event import Event

logger = logging.getLogger(__name__)


async def upsert_events(
    events: list[dict[str, Any]],
) -> list[tuple[str, datetime | None, str]]:
    """
    Upsert a list of event dicts into the ``events`` table using PostgreSQL
    ON CONFLICT (source, source_id) DO UPDATE.

    Each dict must contain at minimum: ``source``, ``source_id``, ``event_type``,
    ``title``, ``latitude``, ``longitude``, ``severity``.

    Returns a list of ``(payload_json, expires_at, event_id)`` tuples for the
    events that were inserted or updated — used by the base class to publish to
    Redis and update the cache.
    """
    if not events:
        return []

    async with AsyncSessionLocal() as session:
        async with session.begin():
            result_tuples: list[tuple[str, datetime | None, str]] = []

            for ev in events:
                # ── Build WKT geography point ─────────────────────────────
                lat = ev.get("latitude")
                lng = ev.get("longitude")
                location = None
                if lat is not None and lng is not None:
                    location = WKTElement(f"POINT({lng} {lat})", srid=4326)

                # ── Ensure id ─────────────────────────────────────────────
                event_id = ev.get("id") or str(uuid.uuid4())

                row = {
                    "id":          event_id,
                    "event_type":  ev.get("event_type", "unknown"),
                    "category":    ev.get("category", ""),
                    "title":       ev.get("title", ""),
                    "description": ev.get("description", ""),
                    "location":    location,
                    "altitude_m":  ev.get("altitude_m"),
                    "heading_deg": ev.get("heading_deg"),
                    "speed_kmh":   ev.get("speed_kmh"),
                    "severity":    ev.get("severity", 1),
                    "source":      ev.get("source", ""),
                    "source_url":  ev.get("source_url"),
                    "source_id":   ev.get("source_id"),
                    "metadata":    ev.get("metadata", {}),
                    "trail":       ev.get("trail"),
                    "expires_at":  ev.get("expires_at"),
                }

                tbl = Event.__table__
                stmt = (
                    pg_insert(tbl)
                    .values(**row)
                    .on_conflict_do_update(
                        constraint="uq_events_source_source_id",
                        set_={
                            "title":       row["title"],
                            "description": row["description"],
                            "location":    row["location"],
                            "altitude_m":  row["altitude_m"],
                            "heading_deg": row["heading_deg"],
                            "speed_kmh":   row["speed_kmh"],
                            "severity":    row["severity"],
                            "metadata":    row["metadata"],
                            "trail":       row["trail"],
                            "expires_at":  row["expires_at"],
                            "updated_at":  datetime.now(timezone.utc),
                        },
                    )
                    .returning(tbl.c.id, tbl.c.expires_at)
                )

                res = await session.execute(stmt)
                returned = res.fetchone()
                if returned:
                    final_id = str(returned[0])
                    expires_at: datetime | None = returned[1]

                    # Build a serialisable payload (no WKTElement)
                    payload = {
                        "id":          final_id,
                        "event_type":  row["event_type"],
                        "category":    row["category"],
                        "title":       row["title"],
                        "description": row["description"],
                        "latitude":    lat,
                        "longitude":   lng,
                        "altitude_m":  row["altitude_m"],
                        "heading_deg": row["heading_deg"],
                        "speed_kmh":   row["speed_kmh"],
                        "severity":    row["severity"],
                        "source":      row["source"],
                        "source_url":  row["source_url"],
                        "source_id":   row["source_id"],
                        "metadata":    row["metadata"],
                        "trail":       row["trail"],
                        "created_at":  datetime.now(timezone.utc).isoformat(),
                        "expires_at":  expires_at.isoformat() if expires_at else None,
                    }
                    result_tuples.append((json.dumps(payload), expires_at, final_id))

            logger.debug("upsert_events: %d rows processed", len(result_tuples))
            return result_tuples

