"""Event deduplication and PostgreSQL upsert logic."""
from __future__ import annotations

import asyncio
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


# Maximum rows per bulk INSERT batch (PostgreSQL handles ~1000 per statement well)
BATCH_SIZE = 500


async def upsert_events(
    events: list[dict[str, Any]],
) -> list[tuple[str, datetime | None, str]]:
    """
    Bulk-upsert a list of event dicts into the ``events`` table using a single
    PostgreSQL INSERT … ON CONFLICT DO UPDATE … RETURNING statement per batch.

    Events are processed in chunks of BATCH_SIZE to keep individual statements
    manageable and to yield the asyncio event loop between chunks.

    Each dict must contain at minimum: ``source``, ``source_id``, ``event_type``,
    ``title``, ``latitude``, ``longitude``, ``severity``.

    Returns a list of ``(payload_json, expires_at, event_id)`` tuples for the
    events that were inserted or updated — used by the base class to publish to
    Redis and update the cache.
    """
    if not events:
        return []

    result_tuples: list[tuple[str, datetime | None, str]] = []
    now = datetime.now(timezone.utc)

    # Pre-build all rows before touching the DB (pure Python, fast)
    rows: list[dict] = []
    coords: list[tuple[float | None, float | None]] = []
    for ev in events:
        lat = ev.get("latitude")
        lng = ev.get("longitude")
        location = None
        if lat is not None and lng is not None:
            location = WKTElement(f"POINT({lng} {lat})", srid=4326)

        event_id = ev.get("id") or str(uuid.uuid4())
        rows.append({
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
        })
        coords.append((lat, lng))

    tbl = Event.__table__

    # Deduplicate by (source, source_id) within this call to prevent
    # "ON CONFLICT DO UPDATE command cannot affect row a second time" from
    # PostgreSQL when the upstream API returns duplicate keys in one batch.
    # Keep last occurrence so we prefer the most-recent position.
    seen_keys: dict[tuple, int] = {}
    for i, row in enumerate(rows):
        key = (row.get("source", ""), row.get("source_id") or row["id"])
        seen_keys[key] = i
    if len(seen_keys) < len(rows):
        dedup_indices = sorted(seen_keys.values())
        rows = [rows[i] for i in dedup_indices]
        coords = [coords[i] for i in dedup_indices]
        logger.debug("upsert_events: deduped %d → %d rows", len(seen_keys) + (len(rows) - len(dedup_indices)), len(rows))

    # Process in batches — yields event loop between batches
    for batch_start in range(0, len(rows), BATCH_SIZE):
        batch_rows = rows[batch_start: batch_start + BATCH_SIZE]
        batch_coords = coords[batch_start: batch_start + BATCH_SIZE]

        # Yield event loop between batches so WS/HTTP requests stay responsive
        await asyncio.sleep(0)

        ins = pg_insert(tbl).values(batch_rows)
        stmt = (
            ins
            .on_conflict_do_update(
                constraint="uq_events_source_source_id",
                set_={
                    "title":       ins.excluded.title,
                    "description": ins.excluded.description,
                    "location":    ins.excluded.location,
                    "altitude_m":  ins.excluded.altitude_m,
                    "heading_deg": ins.excluded.heading_deg,
                    "speed_kmh":   ins.excluded.speed_kmh,
                    "severity":    ins.excluded.severity,
                    "metadata":    ins.excluded.metadata,
                    "trail":       ins.excluded.trail,
                    "expires_at":  ins.excluded.expires_at,
                    "updated_at":  now,
                },
            )
            .returning(tbl.c.id, tbl.c.source_id, tbl.c.expires_at)
        )

        # Build a lookup: source_id → (row_dict, lat, lng)
        row_by_source: dict[str, tuple[dict, float | None, float | None]] = {}
        for row, (lat, lng) in zip(batch_rows, batch_coords):
            sid = row.get("source_id") or row["id"]
            row_by_source[sid] = (row, lat, lng)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                res = await session.execute(stmt)
                returned_rows = res.fetchall()

        for final_id_raw, source_id_raw, expires_at in returned_rows:
            final_id = str(final_id_raw)
            source_id = str(source_id_raw) if source_id_raw is not None else final_id
            entry = row_by_source.get(source_id)
            if entry is None:
                continue
            row, lat, lng = entry

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
                "created_at":  now.isoformat(),
                "expires_at":  expires_at.isoformat() if expires_at else None,
            }
            result_tuples.append((json.dumps(payload), expires_at, final_id))

    logger.debug("upsert_events: %d rows processed in %d batches", len(result_tuples), (len(rows) + BATCH_SIZE - 1) // BATCH_SIZE)
    return result_tuples

