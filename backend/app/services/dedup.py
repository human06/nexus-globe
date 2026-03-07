"""Event deduplication, cross-source merging, clustering and PostgreSQL upsert.

Story 2.7 — three-tier dedup pipeline:

1. **Same-source dedup** (always active):
   INSERT … ON CONFLICT (source, source_id) DO UPDATE

2. **Cross-source news dedup** (news sources only: rss_wires, event_registry, gdelt):
   - Spatial window: 50 km + 2-hour window
   - Title similarity ≥ 70 % (difflib.SequenceMatcher)
   - On match: merge metadata (confirmed_by list, max severity, progressive enrichment)
   - No match: standard insert

3. **Clustering**:
   - Triggered by ``check_and_create_clusters()`` (called from scheduler)
   - > 5 events within 100 km / 4 hours → create / refresh a cluster meta-event

Stale cleanup via ``cleanup_stale_events()`` — removes rows past their ``expires_at``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from geoalchemy2.elements import WKTElement
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.database import AsyncSessionLocal
from app.models.event import Event

logger = logging.getLogger(__name__)

# Maximum rows per bulk INSERT batch
BATCH_SIZE = 500

# News sources that participate in cross-source dedup
_NEWS_SOURCES = frozenset({"rss_wires", "event_registry", "gdelt"})

# Conflict sources for cross-reference dedup (Story 3.7)
_CONFLICT_SOURCES = frozenset({"acled", "military_osint"})

# ---------------------------------------------------------------------------
# Title similarity
# ---------------------------------------------------------------------------

def titles_match(title1: str, title2: str, threshold: float = 0.70) -> bool:
    """Return True when two titles are ≥ *threshold* similar (Levenshtein ratio)."""
    t1 = title1.lower().strip()
    t2 = title2.lower().strip()
    return SequenceMatcher(None, t1, t2).ratio() >= threshold


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

_NEARBY_NEWS_SQL = text("""
    SELECT
        id::text        AS id,
        title           AS title,
        severity        AS severity,
        metadata        AS metadata,
        source          AS source,
        source_id       AS source_id,
        expires_at      AS expires_at
    FROM events
    WHERE event_type = 'news'
      AND created_at >= NOW() - INTERVAL '2 hours'
      AND location IS NOT NULL
      AND ST_DWithin(
            location::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
            :radius_m
          )
    LIMIT 20
""")

_MERGE_SQL = text("""
    UPDATE events
    SET
        severity   = GREATEST(severity, :new_severity),
        metadata   = cast(:new_meta as jsonb),
        updated_at = NOW()
    WHERE id = cast(:event_id as uuid)
    RETURNING id::text, source_id, expires_at
""")

_CLUSTER_COUNT_SQL = text("""
    SELECT COUNT(*) AS cnt
    FROM events
    WHERE event_type NOT IN ('cluster', 'ship', 'flight')
      AND created_at >= NOW() - INTERVAL '4 hours'
      AND location IS NOT NULL
      AND ST_DWithin(
            location::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
            100000
          )
""")

_CLUSTER_EVENTS_SQL = text("""
    SELECT id::text, title, event_type, category, severity,
           ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng
    FROM events
    WHERE event_type NOT IN ('cluster', 'ship', 'flight')
      AND created_at >= NOW() - INTERVAL '4 hours'
      AND location IS NOT NULL
      AND ST_DWithin(
            location::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
            100000
          )
    LIMIT 50
""")

_CLEANUP_SQL = text("""
    DELETE FROM events
    WHERE expires_at IS NOT NULL AND expires_at < NOW()
    RETURNING id
""")

# Story 3.7 — conflict cross-reference dedup SQL
# ACLED battle ↔ Military OSINT report: 50km + 24hr window
_NEARBY_CONFLICT_SQL = text("""
    SELECT
        id::text    AS id,
        title       AS title,
        severity    AS severity,
        metadata    AS metadata,
        source      AS source,
        source_id   AS source_id,
        event_type  AS event_type,
        expires_at  AS expires_at
    FROM events
    WHERE event_type = 'conflict'
      AND source IN ('acled', 'military_osint')
      AND created_at >= NOW() - INTERVAL '24 hours'
      AND location IS NOT NULL
      AND ST_DWithin(
            location::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
            :radius_m
          )
    LIMIT 10
""")

# ACLED/military conflict ↔ news "conflict" category: 100km + 12hr
_NEARBY_CONFLICT_NEWS_SQL = text("""
    SELECT
        id::text    AS id,
        title       AS title,
        severity    AS severity,
        metadata    AS metadata,
        source      AS source,
        source_id   AS source_id,
        event_type  AS event_type,
        expires_at  AS expires_at
    FROM events
    WHERE event_type = 'news'
      AND category LIKE '%conflict%'
      AND created_at >= NOW() - INTERVAL '12 hours'
      AND location IS NOT NULL
      AND ST_DWithin(
            location::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
            :radius_m
          )
    LIMIT 10
""")


# ---------------------------------------------------------------------------
# Cross-source dedup helpers
# ---------------------------------------------------------------------------

async def _find_matching_news(
    session,
    lat: float,
    lng: float,
    title: str,
) -> dict | None:
    """
    Query the DB for a nearby news event that title-matches *title*.

    Returns a row dict {id, title, severity, metadata, source, source_id,
    expires_at} or None.
    """
    result = await session.execute(
        _NEARBY_NEWS_SQL,
        {"lat": lat, "lng": lng, "radius_m": 50_000},
    )
    candidates = result.mappings().all()
    for row in candidates:
        if titles_match(row["title"], title, threshold=0.70):
            return dict(row)
    return None


def _build_merged_metadata(
    existing_meta: dict,
    existing_source: str,
    incoming_event: dict,
) -> dict:
    """
    Merge incoming event's enrichment data into *existing_meta*, producing
    the progressive enrichment tracking structure.
    """
    confirmed_by: list[str] = list(existing_meta.get("confirmed_by", [existing_source]))
    new_source = incoming_event.get("source", "")
    if new_source and new_source not in confirmed_by:
        confirmed_by.append(new_source)

    # Preserve first-seen provenance
    first_seen   = existing_meta.get("first_seen") or existing_meta.get("published_date")
    first_source = existing_meta.get("first_source", existing_source)

    merged = {
        **existing_meta,
        "confirmed_by":          confirmed_by,
        "confirmation_count":    len(confirmed_by),
        "multi_source_confirmed": len(confirmed_by) > 1,
        "first_seen":            first_seen,
        "first_source":          first_source,
    }

    # Pull in enrichment flags from the incoming event if better
    incoming_meta = incoming_event.get("metadata") or {}
    for flag in ("gdelt_enriched", "ai_enriched", "er_concepts"):
        if incoming_meta.get(flag) is not None:
            merged[flag] = incoming_meta[flag]

    # Also keep also_reported_by from RSS tier
    incoming_also = incoming_meta.get("also_reported_by") or []
    existing_also = merged.get("also_reported_by") or []
    merged["also_reported_by"] = list(set(existing_also) | set(incoming_also))

    return merged


async def _cross_source_dedup(
    events: list[dict],
) -> tuple[list[dict], list[tuple[str, datetime | None, str]]]:
    """
    For each geocoded news event:
    - Search DB for a nearby matching event
    - If found: merge metadata and max-severity → return in result_tuples
    - Otherwise: add to ``to_insert`` for normal batch upsert

    Returns (to_insert, result_tuples).
    """
    to_insert: list[dict] = []
    result_tuples: list[tuple[str, datetime | None, str]] = []
    stats = {"new": 0, "merged": 0}

    for ev in events:
        lat = ev["latitude"]
        lng = ev["longitude"]
        title = ev.get("title", "")

        # Read-only lookup in its own session
        async with AsyncSessionLocal() as read_session:
            existing = await _find_matching_news(read_session, lat, lng, title)

        if existing is None:
            to_insert.append(ev)
            stats["new"] += 1
            continue

        # --- Merge into existing event (separate write session) ---
        existing_meta: dict = existing["metadata"] or {}
        merged_meta = _build_merged_metadata(
            existing_meta, existing["source"], ev
        )
        merged_meta_json = json.dumps(merged_meta)

        async with AsyncSessionLocal() as write_session:
            async with write_session.begin():
                res = await write_session.execute(
                    _MERGE_SQL,
                    {
                        "event_id": existing["id"],
                        "new_severity": ev.get("severity", 1),
                        "new_meta": merged_meta_json,
                    },
                )
                row = res.fetchone()

        if row:
            final_id = str(row[0])
            expires_at = row[2]
            payload = {
                "id":          final_id,
                "event_type":  ev.get("event_type", "news"),
                "category":    ev.get("category", ""),
                "title":       existing["title"],   # keep canonical title
                "description": ev.get("description", ""),
                "latitude":    lat,
                "longitude":   lng,
                "severity":    max(existing["severity"], ev.get("severity", 1)),
                "source":      ev.get("source", ""),
                "source_url":  ev.get("source_url"),
                "source_id":   ev.get("source_id"),
                "metadata":    merged_meta,
                "trail":       ev.get("trail"),
                "created_at":  datetime.now(timezone.utc).isoformat(),
                "expires_at":  expires_at.isoformat() if expires_at else None,
            }
            result_tuples.append((json.dumps(payload), expires_at, final_id))
        stats["merged"] += 1

    logger.debug(
        "[dedup] cross-source: %d new, %d merged", stats["new"], stats["merged"]
    )
    return to_insert, result_tuples


# ---------------------------------------------------------------------------
# Conflict cross-reference dedup (Story 3.7)
# ---------------------------------------------------------------------------

_CROSS_LINK_SQL = text("""
    UPDATE events
    SET
        metadata   = jsonb_set(
                        cast(:meta AS jsonb),
                        '{cross_linked_ids}',
                        cast(:linked_ids AS jsonb)
                     ),
        updated_at = NOW()
    WHERE id = cast(:event_id AS uuid)
""")


async def _conflict_cross_reference(events: list[dict]) -> None:
    """
    For conflict events (ACLED / military_osint):
    1. Mark any nearby ACLED ↔ military_osint pairs within 50km / 24hr
    2. Link conflict events to nearby news articles within 100km / 12hr

    Updates metadata.cross_linked_ids in place (best-effort — errors are logged
    but do not block ingestion).
    """
    if not events:
        return

    for ev in events:
        lat  = ev.get("latitude")
        lng  = ev.get("longitude")
        eid  = ev.get("_upserted_id")  # set by batch_upsert when available
        if lat is None or lng is None or eid is None:
            continue

        linked_ids: list[str] = list(
            ev.get("metadata", {}).get("cross_linked_ids") or []
        )

        try:
            async with AsyncSessionLocal() as session:
                # 1. Conflict ↔ conflict (50km / 24hr)
                res = await session.execute(
                    _NEARBY_CONFLICT_SQL,
                    {"lat": lat, "lng": lng, "radius_m": 50_000},
                )
                for row in res.mappings().all():
                    rid = str(row["id"])
                    if rid != str(eid) and rid not in linked_ids:
                        linked_ids.append(rid)

                # 2. Conflict ↔ news "conflict" category (100km / 12hr)
                res2 = await session.execute(
                    _NEARBY_CONFLICT_NEWS_SQL,
                    {"lat": lat, "lng": lng, "radius_m": 100_000},
                )
                for row in res2.mappings().all():
                    rid = str(row["id"])
                    if rid not in linked_ids:
                        linked_ids.append(rid)

            if not linked_ids:
                continue

            # Update metadata.cross_linked_ids on the upserted event
            meta = ev.get("metadata") or {}
            meta["cross_linked_ids"] = linked_ids
            async with AsyncSessionLocal() as write_session:
                async with write_session.begin():
                    await write_session.execute(
                        _CROSS_LINK_SQL,
                        {
                            "event_id":   str(eid),
                            "meta":       json.dumps(meta),
                            "linked_ids": json.dumps(linked_ids),
                        },
                    )
            logger.debug(
                "[dedup] conflict cross-link: event %s → %d links",
                eid, len(linked_ids),
            )

        except Exception as exc:
            logger.debug("[dedup] conflict cross-reference skipped: %s", exc)


# ---------------------------------------------------------------------------
# Core batch upsert (same-source dedup via ON CONFLICT)
# ---------------------------------------------------------------------------

async def _batch_upsert(
    events: list[dict],
) -> list[tuple[str, datetime | None, str]]:
    """
    Bulk-upsert *events* using PostgreSQL INSERT … ON CONFLICT DO UPDATE.
    Same logic as the original ``upsert_events`` core.
    """
    if not events:
        return []

    result_tuples: list[tuple[str, datetime | None, str]] = []
    now = datetime.now(timezone.utc)

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

    # Deduplicate by (source, source_id) within this call
    seen_keys: dict[tuple, int] = {}
    for i, row in enumerate(rows):
        key = (row.get("source", ""), row.get("source_id") or row["id"])
        seen_keys[key] = i
    if len(seen_keys) < len(rows):
        dedup_indices = sorted(seen_keys.values())
        rows   = [rows[i]   for i in dedup_indices]
        coords = [coords[i] for i in dedup_indices]

    tbl = Event.__table__

    for batch_start in range(0, len(rows), BATCH_SIZE):
        batch_rows   = rows[batch_start: batch_start + BATCH_SIZE]
        batch_coords = coords[batch_start: batch_start + BATCH_SIZE]

        await asyncio.sleep(0)

        ins  = pg_insert(tbl).values(batch_rows)
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

        row_by_source: dict[str, tuple[dict, float | None, float | None]] = {}
        for row, (lat, lng) in zip(batch_rows, batch_coords):
            sid = row.get("source_id") or row["id"]
            row_by_source[sid] = (row, lat, lng)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                res = await session.execute(stmt)
                returned_rows = res.fetchall()

        for final_id_raw, source_id_raw, expires_at in returned_rows:
            final_id  = str(final_id_raw)
            source_id = str(source_id_raw) if source_id_raw is not None else final_id
            entry = row_by_source.get(source_id)
            if entry is None:
                continue
            row, lat, lng = entry
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

    return result_tuples


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def upsert_events(
    events: list[dict[str, Any]],
) -> list[tuple[str, datetime | None, str]]:
    """
    Full dedup + upsert pipeline.

    1. Geocoded news events (source in _NEWS_SOURCES, has lat/lng):
       → cross-source dedup (50km + 2hr spatial window, 70% title similarity)
       → merge if match found, else normal insert
    2. All others (ships, flights, disasters, un-geocoded news):
       → fast batch INSERT … ON CONFLICT DO UPDATE

    Returns list of (payload_json, expires_at, event_id) tuples for Redis pub.
    """
    if not events:
        return []

    # Partition: geocoded news vs everything else
    cross_dedup_candidates: list[dict] = []
    batch_candidates: list[dict] = []

    for ev in events:
        is_news = ev.get("source") in _NEWS_SOURCES
        has_coords = ev.get("latitude") is not None and ev.get("longitude") is not None
        if is_news and has_coords:
            cross_dedup_candidates.append(ev)
        else:
            batch_candidates.append(ev)

    result_tuples: list[tuple[str, datetime | None, str]] = []
    stats_incoming = len(events)
    stats_new = 0
    stats_merged = 0
    stats_batch = 0

    # Cross-source dedup pass
    if cross_dedup_candidates:
        unmatched, merge_results = await _cross_source_dedup(cross_dedup_candidates)
        stats_merged = len(merge_results)
        stats_new   += len(unmatched)
        result_tuples.extend(merge_results)
        batch_candidates.extend(unmatched)

    # Batch upsert for all remaining events
    if batch_candidates:
        batch_results = await _batch_upsert(batch_candidates)
        stats_batch = len(batch_results)
        result_tuples.extend(batch_results)

    # Conflict cross-reference dedup (Story 3.7) — mark ACLED↔OSINT↔news links
    conflict_events = [
        ev for ev in events
        if ev.get("source") in _CONFLICT_SOURCES
    ]
    if conflict_events:
        # Attach upserted IDs so cross-reference can update the rows
        id_map = {
            (json.loads(payload).get("source"), json.loads(payload).get("source_id")): eid
            for payload, _, eid in result_tuples
        }
        for ev in conflict_events:
            key = (ev.get("source"), ev.get("source_id"))
            ev["_upserted_id"] = id_map.get(key)
        asyncio.create_task(_conflict_cross_reference(conflict_events))

    total_out = stats_merged + stats_batch
    logger.info(
        "Dedup: %d incoming → %d upserted (%d merged cross-source, %d batch)",
        stats_incoming, total_out, stats_merged, stats_batch,
    )
    return result_tuples


async def cleanup_stale_events() -> int:
    """
    Delete events past their ``expires_at`` timestamp.

    Returns number of rows deleted.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(_CLEANUP_SQL)
            deleted = len(result.fetchall())

    if deleted > 0:
        logger.info("Dedup cleanup: removed %d stale events", deleted)
    return deleted


async def check_and_create_clusters(lat: float, lng: float) -> bool:
    """
    Check whether > 5 events exist within 100 km / 4 hours of (*lat*, *lng*).
    If so, upsert a cluster meta-event aggregating them.

    Returns True if a cluster was created / refreshed.
    """
    async with AsyncSessionLocal() as session:
        # Count nearby events
        count_res = await session.execute(
            _CLUSTER_COUNT_SQL, {"lat": lat, "lng": lng}
        )
        count = count_res.scalar() or 0

        if count <= 5:
            return False

        # Fetch cluster members
        members_res = await session.execute(
            _CLUSTER_EVENTS_SQL, {"lat": lat, "lng": lng}
        )
        members = members_res.mappings().all()

    if not members:
        return False

    # Build cluster meta-event
    member_ids    = [m["id"] for m in members]
    member_titles = [m["title"] for m in members]
    max_severity  = max((m["severity"] for m in members), default=1)
    dominant_type = _mode([m["event_type"] for m in members]) or "news"
    dominant_cat  = _mode([m["category"] for m in members]) or "cluster"

    # Deterministic cluster source_id: bucket ~lat/lng to nearest 0.5°
    lat_bucket = round(lat * 2) / 2
    lng_bucket = round(lng * 2) / 2
    now = datetime.now(timezone.utc)
    hour_bucket = now.strftime("%Y%m%d%H")
    cluster_id = f"cluster_{lat_bucket:.1f}_{lng_bucket:.1f}_{hour_bucket}"

    cluster_event: dict = {
        "event_type": "cluster",
        "category":   dominant_cat,
        "title":      f"Event Cluster — {count} events near {lat:.2f}, {lng:.2f}",
        "description": (
            f"{count} events within 100 km / 4 hours. "
            f"Top headlines: {'; '.join(member_titles[:3])}…"
        ),
        "latitude":   lat,
        "longitude":  lng,
        "severity":   max_severity,
        "source":     "cluster",
        "source_id":  cluster_id,
        "source_url": None,
        "expires_at": now.replace(minute=0, second=0, microsecond=0)
                      .__class__(
                          now.year, now.month, now.day,
                          now.hour + 1 if now.hour < 23 else 23,
                          0, 0, tzinfo=timezone.utc
                      ),
        "metadata": {
            "cluster_count":    count,
            "member_event_ids": member_ids,
            "dominant_type":    dominant_type,
            "first_seen":       now.isoformat(),
        },
    }

    await _batch_upsert([cluster_event])
    logger.info(
        "Dedup cluster: created/refreshed cluster '%s' with %d events (sev %d)",
        cluster_id, count, max_severity,
    )
    return True


def _mode(values: list) -> Any:
    """Return the most common value in *values*."""
    if not values:
        return None
    return max(set(values), key=values.count)
