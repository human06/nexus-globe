"""Event History & Snapshot Service (Story 3.5).

Responsibilities:
- create_snapshot(): capture all active events → store compressed row in event_snapshots
- get_snapshot_at(ts): find nearest snapshot to a given timestamp
- get_history_range(start, end, interval): aggregate snapshot counts per interval
- cleanup_old_snapshots(): prune rows older than 7 days (called by scheduler)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.models.event import Event
from app.models.snapshot import EventSnapshot

logger = logging.getLogger(__name__)

# How many days to retain snapshots
SNAPSHOT_RETENTION_DAYS = 7


# ── Snapshot creation ─────────────────────────────────────────────────────────

async def create_snapshot() -> dict[str, Any]:
    """
    Capture all currently active events and persist a compressed snapshot row.

    "Active" = not expired (expires_at IS NULL OR expires_at > now()).

    Returns a dict with capture stats.
    """
    async with get_db_session() as db:
        now = datetime.now(timezone.utc)

        # Fetch all active events — only the columns we need for the snapshot
        stmt = select(
            Event.id,
            Event.event_type,
            Event.severity,
            Event.title,
            # Extract lat/lng from the PostGIS POINT
            func.ST_Y(func.ST_GeomFromWKB(func.ST_AsBinary(Event.location))).label("lat"),
            func.ST_X(func.ST_GeomFromWKB(func.ST_AsBinary(Event.location))).label("lng"),
        ).where(
            (Event.expires_at.is_(None)) | (Event.expires_at > now)
        )

        result = await db.execute(stmt)
        rows = result.all()

        # Compress to minimal dicts
        summaries: list[dict] = []
        layer_counts: dict[str, int] = {}
        for row in rows:
            summaries.append({
                "id":    str(row.id),
                "type":  row.event_type,
                "lat":   round(float(row.lat), 4) if row.lat is not None else None,
                "lng":   round(float(row.lng), 4) if row.lng is not None else None,
                "sev":   row.severity,
                "title": row.title[:120] if row.title else "",
            })
            layer_counts[row.event_type] = layer_counts.get(row.event_type, 0) + 1

        snapshot = EventSnapshot(
            snapshot_time=now,
            event_count=len(summaries),
            layer_counts=layer_counts,
            events=summaries,
        )
        db.add(snapshot)
        await db.commit()
        await db.refresh(snapshot)

        size_bytes = len(str(summaries).encode())
        logger.info(
            "Snapshot: captured %d events at %s (%.1f KB compressed)",
            len(summaries),
            now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            size_bytes / 1024,
        )
        return {
            "snapshot_id": str(snapshot.id),
            "snapshot_time": now.isoformat(),
            "event_count": len(summaries),
            "layer_counts": layer_counts,
            "size_bytes": size_bytes,
        }


# ── Historical query ──────────────────────────────────────────────────────────

async def get_snapshot_at(timestamp: datetime) -> dict[str, Any] | None:
    """
    Return the nearest snapshot to *timestamp*.

    Searches ±4 hours; returns None if no snapshot found in that window.
    """
    async with get_db_session() as db:
        # Find the snapshot whose snapshot_time is closest to requested timestamp
        delta = func.abs(
            func.extract("epoch", EventSnapshot.snapshot_time - timestamp)
        )
        stmt = (
            select(EventSnapshot)
            .where(
                EventSnapshot.snapshot_time >= timestamp - timedelta(hours=4),
                EventSnapshot.snapshot_time <= timestamp + timedelta(hours=4),
            )
            .order_by(delta)
            .limit(1)
        )
        result = await db.execute(stmt)
        snap = result.scalar_one_or_none()

        if snap is None:
            return None

        return {
            "snapshot_id":    str(snap.id),
            "snapshot_time":  snap.snapshot_time.isoformat(),
            "requested_time": timestamp.isoformat(),
            "event_count":    snap.event_count,
            "layer_counts":   snap.layer_counts,
            "events":         snap.events,
        }


async def get_history_range(
    start: datetime, end: datetime, interval_hours: int = 1
) -> list[dict[str, Any]]:
    """
    Return a list of snapshot summaries (counts per layer) bucketed by *interval_hours*.

    Used by the Timeline scrubber to render event density over time.
    For each interval bucket, returns the counts from the nearest available snapshot.
    """
    async with get_db_session() as db:
        # Fetch all snapshots in the range
        stmt = (
            select(
                EventSnapshot.snapshot_time,
                EventSnapshot.event_count,
                EventSnapshot.layer_counts,
            )
            .where(
                EventSnapshot.snapshot_time >= start,
                EventSnapshot.snapshot_time <= end,
            )
            .order_by(EventSnapshot.snapshot_time.asc())
        )
        result = await db.execute(stmt)
        rows = result.all()

        if not rows:
            return []

        # Group into interval buckets
        buckets: list[dict] = []
        bucket_start = start
        interval = timedelta(hours=interval_hours)

        while bucket_start < end:
            bucket_end = bucket_start + interval
            # Find snaps within this bucket
            bucket_snaps = [
                r for r in rows
                if bucket_start <= r.snapshot_time < bucket_end
            ]
            if bucket_snaps:
                # Use the most recent snapshot in the bucket
                latest = bucket_snaps[-1]
                buckets.append({
                    "bucket_start":  bucket_start.isoformat(),
                    "bucket_end":    bucket_end.isoformat(),
                    "event_count":   latest.event_count,
                    "layer_counts":  latest.layer_counts,
                })
            else:
                buckets.append({
                    "bucket_start": bucket_start.isoformat(),
                    "bucket_end":   bucket_end.isoformat(),
                    "event_count":  0,
                    "layer_counts": {},
                })
            bucket_start = bucket_end

        return buckets


# ── Cleanup ───────────────────────────────────────────────────────────────────

async def cleanup_old_snapshots() -> int:
    """Delete snapshots older than SNAPSHOT_RETENTION_DAYS days."""
    async with get_db_session() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=SNAPSHOT_RETENTION_DAYS)
        stmt = delete(EventSnapshot).where(EventSnapshot.snapshot_time < cutoff)
        result = await db.execute(stmt)
        await db.commit()
        if result.rowcount:
            logger.info(
                "[snapshot] Pruned %d old snapshots (older than %d days)",
                result.rowcount,
                SNAPSHOT_RETENTION_DAYS,
            )
        return result.rowcount
