"""Abstract base class for all data ingestion services."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any


class BaseIngestionService(ABC):
    """
    All ingestion services inherit from this class.

    Subclasses must implement:
    - ``source_name``: human-readable data source identifier
    - ``poll_interval_seconds``: how often the scheduler invokes ``ingest()``
    - ``fetch_raw()``: retrieve raw data from the external API
    - ``normalize()``: convert raw data to a list of GlobeEventCreate dicts
    """

    source_name: str = "unknown"
    poll_interval_seconds: int = 60

    def __init__(self) -> None:
        self.logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )

    @abstractmethod
    async def fetch_raw(self) -> Any:
        """Fetch raw data from the upstream source. Must be overridden."""
        ...

    @abstractmethod
    async def normalize(self, raw: Any) -> list[dict]:
        """
        Convert raw data to a list of event dicts compatible with
        GlobeEventCreate.  Must be overridden.
        """
        ...

    async def ingest(self) -> list[dict]:
        """
        Orchestrates a full ingestion cycle:
        1. fetch_raw()
        2. normalize()
        3. Return normalised events for persistence / broadcasting.
        """
        self.logger.info("[%s] Starting ingestion cycle", self.source_name)
        raw = await self.fetch_raw()
        events = await self.normalize(raw)
        self.logger.info(
            "[%s] Ingestion complete — %d events", self.source_name, len(events)
        )
        return events
