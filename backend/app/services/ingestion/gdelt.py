"""Stub ingestion service for GDELT Project (global news events)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)


class GDELTIngestionService(BaseIngestionService):
    source_name = "gdelt"
    poll_interval_seconds = 300

    async def fetch_raw(self) -> Any:
        # TODO: implement HTTP fetch from GDELT Project (global news events)
        logger.info("[gdelt] fetch_raw called — not yet implemented")
        return None

    async def normalize(self, raw: Any) -> list[dict]:
        # TODO: parse raw API response and return list of event dicts
        logger.info("[gdelt] normalize called — not yet implemented")
        return []
