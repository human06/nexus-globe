"""Async Redis client — connection lifecycle, pub/sub helpers, and event cache."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import AsyncIterator

import redis.asyncio as aioredis
from redis.asyncio.client import PubSub

from app.config import settings

logger = logging.getLogger(__name__)

# ── Channel naming convention ─────────────────────────────────────────────────
CHANNEL_PREFIX = "layer:"
# e.g.  layer:flight  |  layer:news  |  layer:ship  |  layer:satellite …

# ── Module-level client (initialised in startup, torn down in shutdown) ────────
_redis: aioredis.Redis | None = None


# ── Lifecycle helpers (called from main.py lifespan) ─────────────────────────

async def init_redis() -> None:
    """Create the async Redis connection pool and verify connectivity."""
    global _redis
    _redis = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=5,
    )
    # Verify the connection is reachable right away
    await _redis.ping()
    logger.info("Redis connected: %s", settings.redis_url)


async def close_redis() -> None:
    """Close the Redis connection pool gracefully."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("Redis connection closed.")


def get_redis() -> aioredis.Redis:
    """Return the module-level Redis client (must call init_redis first)."""
    if _redis is None:
        raise RuntimeError("Redis is not initialised — call init_redis() at startup.")
    return _redis


# ── Health check helper ───────────────────────────────────────────────────────

async def redis_ping() -> bool:
    """Return True if Redis responds to PING, False otherwise."""
    try:
        client = get_redis()
        return await client.ping()
    except Exception as exc:
        logger.warning("Redis ping failed: %s", exc)
        return False


# ── Pub/Sub helpers ───────────────────────────────────────────────────────────

def channel_name(event_type: str) -> str:
    """Return the Redis channel name for a given event type."""
    return f"{CHANNEL_PREFIX}{event_type}"


async def publish_event(event_type: str, payload_json: str) -> None:
    """
    Publish a JSON-serialised event to the appropriate layer channel.

    Args:
        event_type: e.g. "flight", "news", "ship"
        payload_json: JSON string of the event (model_dump_json() output)
    """
    client = get_redis()
    channel = channel_name(event_type)
    await client.publish(channel, payload_json)
    logger.debug("Published to %s", channel)


async def subscribe_channel(event_type: str) -> AsyncIterator[str]:
    """
    Subscribe to a layer channel and yield raw JSON message strings.

    Creates a **new** dedicated PubSub object per subscription so that
    each consumer gets its own listener and can be independently cancelled.

    Usage::

        async for message_json in subscribe_channel("flight"):
            data = json.loads(message_json)
            ...
    """
    client = get_redis()
    pubsub: PubSub = client.pubsub()
    channel = channel_name(event_type)
    await pubsub.subscribe(channel)
    logger.info("Subscribed to Redis channel: %s", channel)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                yield message["data"]
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        logger.info("Unsubscribed from Redis channel: %s", channel)


# ── Event cache helpers ───────────────────────────────────────────────────────

async def cache_event(
    event_id: str,
    event_type: str,
    payload_json: str,
    expires_at: datetime | None = None,
    default_ttl: int = 300,
) -> None:
    """
    Cache a serialised event in Redis.

    TTL is derived from ``expires_at`` (seconds remaining from now).
    Falls back to ``default_ttl`` seconds (5 min) when not provided.

    Args:
        event_id:     UUID string of the event.
        event_type:   e.g. "flight"  — used to build a set of active IDs per layer.
        payload_json: JSON string to cache.
        expires_at:   Optional datetime when this event expires (UTC-aware).
        default_ttl:  Fallback TTL in seconds.
    """
    client = get_redis()

    # Calculate TTL
    ttl: int = default_ttl
    if expires_at is not None:
        now = datetime.now(timezone.utc)
        remaining = int((expires_at - now).total_seconds())
        ttl = max(remaining, 1)  # never set a negative / zero TTL

    key = f"event:{event_id}"
    await client.setex(key, ttl, payload_json)

    # Also keep a set of active event IDs per layer for snapshot delivery
    layer_set_key = f"layer_ids:{event_type}"
    await client.sadd(layer_set_key, event_id)
    # Give the set a slightly longer TTL so it outlives individual events
    await client.expire(layer_set_key, ttl + 60)


async def get_cached_event(event_id: str) -> str | None:
    """Return the cached JSON string for an event, or None if expired/missing."""
    client = get_redis()
    return await client.get(f"event:{event_id}")


async def get_layer_snapshot(event_type: str) -> list[str]:
    """
    Return a list of cached JSON strings for all active events of a given type.

    Used by the WebSocket server to send an initial snapshot to new subscribers.
    """
    client = get_redis()
    layer_set_key = f"layer_ids:{event_type}"
    event_ids: set[str] = await client.smembers(layer_set_key)

    if not event_ids:
        return []

    # Fetch all keys in one pipeline round-trip
    pipe = client.pipeline()
    for eid in event_ids:
        pipe.get(f"event:{eid}")
    results: list[str | None] = await pipe.execute()

    # Filter out entries that have expired (None)
    return [r for r in results if r is not None]
