"""Stub ingestion service for CelesTrak (TLE satellite data)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)


class CelesTrakIngestionService(BaseIngestionService):
    source_name = "celestrak"
    poll_interval_seconds = 60

    async def fetch_raw(self) -> Any:
        # TODO: implement HTTP fetch from CelesTrak (TLE satellite data)
        logger.info("[celestrak] fetch_raw called — not yet implemented")
        return None

    async def normalize(self, raw: Any) -> list[dict]:
        # TODO: parse raw API response and return list of event dicts
        logger.info("[celestrak] normalize called — not yet implemented")
        return []
