"""Stub ingestion service for OpenSky Network (ADS-B flight data)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)


class OpenSkyIngestionService(BaseIngestionService):
    source_name = "opensky"
    poll_interval_seconds = 15

    async def fetch_raw(self) -> Any:
        # TODO: implement HTTP fetch from OpenSky Network (ADS-B flight data)
        logger.info("[opensky] fetch_raw called — not yet implemented")
        return None

    async def normalize(self, raw: Any) -> list[dict]:
        # TODO: parse raw API response and return list of event dicts
        logger.info("[opensky] normalize called — not yet implemented")
        return []
