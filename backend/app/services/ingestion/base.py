"""Abstract base class for all data ingestion services."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any


class BaseIngestionService(ABC):
    """
    All ingestion services inherit from this class.

    Subclasses must implement:
    - ``source_name``            : stable identifier used for Redis channels
    - ``poll_interval_seconds``  : scheduler frequency
    - ``fetch_raw()``            : retrieve raw data from the external API
    - ``normalize(raw)``         : convert raw → list[dict] (GlobeEventCreate-compat)

    The base ``ingest()`` orchestrates the full pipeline:
        fetch_raw → normalize → upsert → publish → log stats
    """

    source_name: str = "unknown"
    poll_interval_seconds: int = 60

    def __init__(self) -> None:
        self.logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )

    @abstractmethod
    async def fetch_raw(self) -> Any:
        """Fetch raw data from the upstream source."""
        ...

    @abstractmethod
    async def normalize(self, raw: Any) -> list[dict]:
        """
        Convert raw API response to a list of event dicts that are
        compatible with ``GlobeEventCreate``.
        """
        ...

    async def ingest(self) -> int:
        """
        Full ingestion pipeline:
        1. ``fetch_raw()``
        2. ``normalize()``
        3. Upsert events into PostgreSQL (ON CONFLICT source+source_id DO UPDATE)
        4. Publish each upserted event to Redis ``layer:{source_name}`` channel
        5. Cache each event in Redis with its TTL

        Returns the number of events upserted.
        """
        # Deferred imports to avoid circular deps at module load time
        from app.services.dedup import upsert_events
        from app.db.redis import publish_event, cache_event

        self.logger.info("[%s] Starting ingestion cycle", self.source_name)

        raw = await self.fetch_raw()
        if raw is None:
            self.logger.warning("[%s] fetch_raw returned None — skipping", self.source_name)
            return 0

        events = await self.normalize(raw)
        if not events:
            self.logger.info("[%s] No events after normalisation", self.source_name)
            return 0

        # Persist + get back serialised payloads for broadcasting
        upserted = await upsert_events(events)

        # Publish each upserted event to Redis
        for payload_json, expires_at, event_id in upserted:
            try:
                await publish_event(self.source_name, payload_json)
                await cache_event(
                    event_id=event_id,
                    event_type=self.source_name,
                    payload_json=payload_json,
                    expires_at=expires_at,
                )
            except Exception as exc:
                self.logger.warning("[%s] Redis publish failed: %s", self.source_name, exc)

        self.logger.info(
            "[%s] Ingestion complete — %d/%d events upserted",
            self.source_name,
            len(upserted),
            len(events),
        )
        return len(upserted)

