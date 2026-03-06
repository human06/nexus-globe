"""Stub ingestion service for USGS Earthquake Hazards Program."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)


class USGSIngestionService(BaseIngestionService):
    source_name = "usgs"
    poll_interval_seconds = 60

    async def fetch_raw(self) -> Any:
        # TODO: implement HTTP fetch from USGS Earthquake Hazards Program
        logger.info("[usgs] fetch_raw called — not yet implemented")
        return None

    async def normalize(self, raw: Any) -> list[dict]:
        # TODO: parse raw API response and return list of event dicts
        logger.info("[usgs] normalize called — not yet implemented")
        return []
