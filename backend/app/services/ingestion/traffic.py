"""Stub ingestion service for Google Maps Traffic (stub)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)


class TrafficIngestionService(BaseIngestionService):
    source_name = "traffic"
    poll_interval_seconds = 120

    async def fetch_raw(self) -> Any:
        # TODO: implement HTTP fetch from Google Maps Traffic (stub)
        logger.info("[traffic] fetch_raw called — not yet implemented")
        return None

    async def normalize(self, raw: Any) -> list[dict]:
        # TODO: parse raw API response and return list of event dicts
        logger.info("[traffic] normalize called — not yet implemented")
        return []
