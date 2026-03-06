"""APScheduler setup — registers all ingestion services and starts the clock."""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.ingestion.opensky import OpenSkyIngestionService
from app.services.ingestion.celestrak import CelesTrakIngestionService
from app.services.ingestion.gdelt import GDELTIngestionService
from app.services.ingestion.usgs import USGSIngestionService
from app.services.ingestion.eonet import EONETIngestionService
from app.services.ingestion.aishub import AISHubIngestionService
from app.services.ingestion.acled import ACLEDIngestionService
from app.services.ingestion.traffic import TrafficIngestionService

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# All ingestion service instances
_services = [
    OpenSkyIngestionService(),
    CelesTrakIngestionService(),
    GDELTIngestionService(),
    USGSIngestionService(),
    EONETIngestionService(),
    AISHubIngestionService(),
    ACLEDIngestionService(),
    TrafficIngestionService(),
]


async def _run_service(service) -> None:
    """Wrapper that calls service.ingest() and logs any errors."""
    try:
        await service.ingest()
    except Exception as exc:
        logger.exception(
            "[scheduler] Error in %s ingestion: %s", service.source_name, exc
        )


def start_scheduler() -> AsyncIOScheduler:
    """Create the APScheduler, register all jobs, and start it."""
    global _scheduler
    _scheduler = AsyncIOScheduler()

    for svc in _services:
        _scheduler.add_job(
            _run_service,
            "interval",
            seconds=svc.poll_interval_seconds,
            args=[svc],
            id=f"ingest_{svc.source_name}",
            replace_existing=True,
        )
        logger.info(
            "[scheduler] Registered '%s' every %ds",
            svc.source_name,
            svc.poll_interval_seconds,
        )

    _scheduler.start()
    logger.info("[scheduler] APScheduler started with %d jobs.", len(_services))
    return _scheduler
