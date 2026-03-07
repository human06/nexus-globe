"""Abstract base class for all data ingestion services."""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
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
        from app.db.redis import publish_event, get_redis

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

        # Cache events in Redis via pipeline in chunks to yield the event loop
        # Only publish the most-recent 200 to avoid flooding WS subscribers
        PUBLISH_LIMIT = 200
        REDIS_CHUNK = 500
        try:
            client = get_redis()
            for chunk_start in range(0, len(upserted), REDIS_CHUNK):
                await asyncio.sleep(0)  # yield event loop between chunks
                chunk = upserted[chunk_start: chunk_start + REDIS_CHUNK]
                pipe = client.pipeline(transaction=False)
                for payload_json, expires_at, event_id in chunk:
                    ttl = 300
                    if expires_at is not None:
                        remaining = int((expires_at - datetime.now(timezone.utc)).total_seconds())
                        ttl = max(remaining, 1)
                    pipe.setex(f"event:{event_id}", ttl, payload_json)
                    pipe.sadd(f"layer_ids:{self.source_name}", event_id)
                    pipe.expire(f"layer_ids:{self.source_name}", ttl + 60)
                await pipe.execute()
        except Exception as exc:
            self.logger.warning("[%s] Redis cache pipeline failed: %s", self.source_name, exc)

        # Publish a sample to the Redis pub/sub channel so live clients get updates
        await asyncio.sleep(0)
        for payload_json, _, _ in upserted[:PUBLISH_LIMIT]:
            try:
                await publish_event(self.source_name, payload_json)
            except Exception as exc:
                self.logger.warning("[%s] Redis publish failed: %s", self.source_name, exc)
                break

        self.logger.info(
            "[%s] Ingestion complete — %d/%d events upserted",
            self.source_name,
            len(upserted),
            len(events),
        )
        return len(upserted)

