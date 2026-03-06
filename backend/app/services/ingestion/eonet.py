"""Stub ingestion service for NASA EONET (natural disaster events)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)


class EONETIngestionService(BaseIngestionService):
    source_name = "eonet"
    poll_interval_seconds = 300

    async def fetch_raw(self) -> Any:
        # TODO: implement HTTP fetch from NASA EONET (natural disaster events)
        logger.info("[eonet] fetch_raw called — not yet implemented")
        return None

    async def normalize(self, raw: Any) -> list[dict]:
        # TODO: parse raw API response and return list of event dicts
        logger.info("[eonet] normalize called — not yet implemented")
        return []
