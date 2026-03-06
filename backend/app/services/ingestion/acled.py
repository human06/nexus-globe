"""Stub ingestion service for ACLED (Armed Conflict Location & Event)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)


class ACLEDIngestionService(BaseIngestionService):
    source_name = "acled"
    poll_interval_seconds = 3600

    async def fetch_raw(self) -> Any:
        # TODO: implement HTTP fetch from ACLED (Armed Conflict Location & Event)
        logger.info("[acled] fetch_raw called — not yet implemented")
        return None

    async def normalize(self, raw: Any) -> list[dict]:
        # TODO: parse raw API response and return list of event dicts
        logger.info("[acled] normalize called — not yet implemented")
        return []
