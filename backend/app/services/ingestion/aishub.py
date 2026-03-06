"""Stub ingestion service for AISHub (AIS ship tracking)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)


class AISHubIngestionService(BaseIngestionService):
    source_name = "aishub"
    poll_interval_seconds = 30

    async def fetch_raw(self) -> Any:
        # TODO: implement HTTP fetch from AISHub (AIS ship tracking)
        logger.info("[aishub] fetch_raw called — not yet implemented")
        return None

    async def normalize(self, raw: Any) -> list[dict]:
        # TODO: parse raw API response and return list of event dicts
        logger.info("[aishub] normalize called — not yet implemented")
        return []
