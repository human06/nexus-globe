"""APScheduler setup — registers all ingestion services and starts the clock."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.ingestion.flightradar import FlightRadarIngestionService
from app.services.ingestion.celestrak import CelesTrakIngestionService
from app.services.ingestion.rss_wires import RSSWireService
from app.services.ingestion.event_registry import EventRegistryService
from app.services.ingestion.gdelt import GDELTIngestionService
from app.services.ingestion.usgs import USGSIngestionService
from app.services.ingestion.eonet import EONETIngestionService
from app.services.ingestion.aisstream import AISStreamIngestionService
from app.services.ingestion.acled import ACLEDIngestionService
from app.services.ingestion.military_osint import MilitaryOSINTService
from app.services.ingestion.traffic import TrafficIngestionService
from app.services.dedup import cleanup_stale_events
from app.services.ai_analyzer import get_analyzer
from app.services.snapshot_service import create_snapshot, cleanup_old_snapshots

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# All ingestion service instances
_services = [
    FlightRadarIngestionService(),
    CelesTrakIngestionService(),
    RSSWireService(),
    EventRegistryService(),
    GDELTIngestionService(),
    USGSIngestionService(),
    EONETIngestionService(),
    AISStreamIngestionService(),
    ACLEDIngestionService(),
    MilitaryOSINTService(),
    TrafficIngestionService(),
]

# Per-service runtime stats (populated by _run_service)
_service_stats: dict[str, dict] = {
    svc.source_name: {
        "name":             svc.source_name,
        "interval_seconds": svc.poll_interval_seconds,
        "last_run":         None,
        "last_count":       None,
        "last_error":       None,
        "status":           "pending",
    }
    for svc in _services
}


async def _run_service(service) -> None:
    """Wrapper that calls service.ingest() and logs each cycle."""
    logger.info(
        "Scheduler: running %s (interval: %ds)",
        service.source_name,
        service.poll_interval_seconds,
    )
    stats = _service_stats.get(service.source_name, {})
    stats["status"] = "running"
    try:
        count = await service.ingest()
        stats["last_run"]   = datetime.now(timezone.utc).isoformat()
        stats["last_count"] = count or 0
        stats["last_error"] = None
        stats["status"]     = "ok"
        logger.info(
            "Scheduler: %s completed — %d events upserted",
            service.source_name,
            count or 0,
        )
    except Exception as exc:
        stats["last_run"]   = datetime.now(timezone.utc).isoformat()
        stats["last_error"] = str(exc)
        stats["status"]     = "error"
        logger.exception(
            "[scheduler] Error in %s ingestion: %s", service.source_name, exc
        )


async def _run_cleanup() -> None:
    """Periodic stale-event + old-snapshot cleanup job."""
    try:
        deleted = await cleanup_stale_events()
        if deleted:
            logger.info("[scheduler] Stale-event cleanup: %d rows removed", deleted)
    except Exception as exc:
        logger.exception("[scheduler] Stale-event cleanup failed: %s", exc)

    try:
        pruned = await cleanup_old_snapshots()
        if pruned:
            logger.info("[scheduler] Old-snapshot cleanup: %d rows removed", pruned)
    except Exception as exc:
        logger.exception("[scheduler] Old-snapshot cleanup failed: %s", exc)


async def _run_snapshot() -> None:
    """Periodic snapshot of all active events (Story 3.5)."""
    try:
        stats = await create_snapshot()
        logger.info(
            "[snapshot] Captured %d events (%.1f KB) at %s",
            stats["event_count"],
            stats["size_bytes"] / 1024,
            stats["snapshot_time"],
        )
    except Exception as exc:
        logger.exception("[scheduler] Snapshot creation failed: %s", exc)


async def _run_ai_enrichment() -> None:
    """Periodic AI geocoding + enrichment cycle."""
    analyzer = get_analyzer()
    if not analyzer.enabled:
        return
    try:
        result = await analyzer.run_enrichment_cycle(geocode_limit=10, enrich_limit=10)
        if result.get("geocoded") or result.get("enriched"):
            logger.info(
                "[scheduler] AI enrichment: geocoded=%d enriched=%d elapsed=%dms",
                result["geocoded"], result["enriched"], result["elapsed_ms"],
            )
    except Exception as exc:
        logger.exception("[scheduler] AI enrichment cycle failed: %s", exc)


def start_scheduler() -> AsyncIOScheduler:
    """Create the APScheduler, register all jobs, and start it."""
    global _scheduler
    # misfire_grace_time=None: run jobs even if they're very late (e.g. at startup)
    _scheduler = AsyncIOScheduler(job_defaults={"misfire_grace_time": None})

    for svc in _services:
        _scheduler.add_job(
            _run_service,
            "interval",
            seconds=svc.poll_interval_seconds,
            args=[svc],
            id=f"ingest_{svc.source_name}",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc),  # fire immediately on startup
        )
        logger.info(
            "[scheduler] Registered '%s' every %ds",
            svc.source_name,
            svc.poll_interval_seconds,
        )

    # Stale event cleanup — runs every 5 minutes
    _scheduler.add_job(
        _run_cleanup,
        "interval",
        seconds=300,
        id="dedup_cleanup",
        replace_existing=True,
    )
    logger.info("[scheduler] Registered stale-event cleanup every 300s")

    # Event snapshot — runs every 15 minutes (Story 3.5)
    _scheduler.add_job(
        _run_snapshot,
        "interval",
        seconds=900,
        id="event_snapshot",
        replace_existing=True,
    )
    logger.info("[scheduler] Registered event snapshot every 900s")

    # AI enrichment cycle — runs every 60 seconds
    _scheduler.add_job(
        _run_ai_enrichment,
        "interval",
        seconds=60,
        id="ai_enrichment",
        replace_existing=True,
    )
    logger.info("[scheduler] Registered AI enrichment cycle every 60s")

    _scheduler.start()
    logger.info("[scheduler] APScheduler started with %d jobs.", len(_services) + 3)
    return _scheduler


def stop_scheduler() -> None:
    """Gracefully shut down the APScheduler (waits for running jobs to finish)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=True)
        logger.info("[scheduler] APScheduler stopped.")
    _scheduler = None


def get_scheduler() -> AsyncIOScheduler | None:
    """Return the running scheduler instance (or None if not started)."""
    return _scheduler


def get_service_statuses() -> list[dict]:
    """Return runtime stats for all registered ingestion services (Story 2.9)."""
    return list(_service_stats.values())

