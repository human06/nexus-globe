"""WebSocket server — Story 1.4.

Architecture
────────────
• One Redis PubSub listener task per active layer channel.
  The task is created when the first client subscribes and cancelled when
  the last client unsubscribes.  It broadcasts incoming Redis messages to
  all currently-subscribed WebSocket clients.

• One heartbeat task per connected client (ping every 30 s).

Message protocol
────────────────
Client → Server (JSON):
  { "action": "subscribe",   "layers": ["flight", "news"] }
  { "action": "unsubscribe", "layers": ["flight"] }
  { "action": "get_detail",  "event_id": "<uuid>" }

Server → Client (JSON):
  { "type": "snapshot",     "data": [ ...GlobeEvent ] }
  { "type": "event_update", "data": { ...GlobeEvent } }
  { "type": "event_batch",  "data": [ ...GlobeEvent ] }
  { "type": "event_remove", "data": { "id": "..." } }
  { "type": "ping" }
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

from fastapi.websockets import WebSocket, WebSocketState
from sqlalchemy import text

from app.db.database import AsyncSessionLocal
from app.db.redis import get_layer_snapshot, subscribe_channel

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30  # seconds between pings
MAX_SNAPSHOT_EVENTS = 2000  # cap per-layer snapshot; each flight ~400 B → ~800 KB total


class ConnectionManager:
    """
    Manages all active WebSocket connections and bridges them to Redis PubSub.

    Internal state
    ──────────────
    _connections    : WebSocket → set of subscribed layer names
    _layer_sockets  : layer name → set of WebSockets
    _redis_tasks    : layer name → asyncio.Task (one Redis listener per layer)
    _heartbeat_tasks: WebSocket → asyncio.Task (one heartbeat per connection)
    """

    def __init__(self) -> None:
        self._connections: dict[WebSocket, set[str]] = {}
        self._layer_sockets: dict[str, set[WebSocket]] = defaultdict(set)
        self._redis_tasks: dict[str, asyncio.Task] = {}
        self._heartbeat_tasks: dict[WebSocket, asyncio.Task] = {}

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self._connections[websocket] = set()
        self._heartbeat_tasks[websocket] = asyncio.create_task(
            self._heartbeat(websocket)
        )
        logger.info(
            "WebSocket connected — total connections: %d",
            len(self._connections),
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """Clean up all subscriptions and tasks for a disconnected client."""
        # Cancel heartbeat
        task = self._heartbeat_tasks.pop(websocket, None)
        if task:
            task.cancel()

        # Unsubscribe from all layers
        layers = self._connections.pop(websocket, set()).copy()
        for layer in layers:
            await self._remove_from_layer(websocket, layer)

        logger.info(
            "WebSocket disconnected — total connections: %d",
            len(self._connections),
        )

    # ── Subscription management ───────────────────────────────────────────────

    async def subscribe(self, websocket: WebSocket, layers: list[str]) -> None:
        """
        Subscribe a client to one or more layer channels.

        For each layer:
        1. Register the WebSocket in the per-layer socket set.
        2. Ensure a Redis listener task is running for that layer.
        3. Send a snapshot of currently-cached events for that layer.
        """
        for layer in layers:
            if layer in self._connections.get(websocket, set()):
                continue  # already subscribed

            self._connections.setdefault(websocket, set()).add(layer)
            self._layer_sockets[layer].add(websocket)
            logger.info("Client subscribed to layer '%s'", layer)

            # Start Redis listener if this is the first subscriber
            if layer not in self._redis_tasks or self._redis_tasks[layer].done():
                self._redis_tasks[layer] = asyncio.create_task(
                    self._redis_listener(layer)
                )

            # Send snapshot of existing events for this layer
            await self._send_snapshot(websocket, layer)

    async def unsubscribe(self, websocket: WebSocket, layers: list[str]) -> None:
        """Unsubscribe a client from one or more layer channels."""
        for layer in layers:
            self._connections.get(websocket, set()).discard(layer)
            await self._remove_from_layer(websocket, layer)

    async def _remove_from_layer(self, websocket: WebSocket, layer: str) -> None:
        """Remove a WebSocket from a layer; cancel Redis task if no subscribers left."""
        self._layer_sockets[layer].discard(websocket)
        if not self._layer_sockets[layer]:
            # Last subscriber gone — cancel the Redis listener
            task = self._redis_tasks.pop(layer, None)
            if task and not task.done():
                task.cancel()
                logger.debug("Cancelled Redis listener for layer '%s'", layer)

    # ── Outbound push helpers ─────────────────────────────────────────────────

    async def push(self, websocket: WebSocket, message: dict) -> None:
        """Send a JSON message to a single WebSocket, handling disconnect."""
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_text(json.dumps(message))
        except Exception as exc:
            logger.debug("Send failed (%s), disconnecting client", exc)
            await self.disconnect(websocket)

    async def push_to_layer(self, layer: str, message: dict) -> None:
        """Broadcast a message to every WebSocket subscribed to a layer."""
        payload = json.dumps(message)
        dead: list[WebSocket] = []
        for ws in set(self._layer_sockets.get(layer, set())):
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(payload)
                else:
                    dead.append(ws)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)

    # ── Snapshot delivery ─────────────────────────────────────────────────────

    async def _send_snapshot(self, websocket: WebSocket, layer: str) -> None:
        """
        Fetch all cached events for a layer from Redis and push them as a
        ``snapshot`` message to the newly-subscribed client.
        Falls back to a direct DB query if Redis cache is cold/empty.
        """
        try:
            raw_events = await get_layer_snapshot(layer)
            if raw_events:
                # Limit snapshot size to avoid giant WS frames that freeze the event loop
                raw_events = raw_events[:MAX_SNAPSHOT_EVENTS]
                events = [json.loads(raw) for raw in raw_events]
            else:
                # Redis cold — query DB directly for non-expired events
                logger.info("Redis cold for layer '%s', falling back to DB", layer)
                events = await self._db_snapshot(layer)
                # Repopulate Redis cache for next time
                for ev in events:
                    try:
                        from app.db.redis import cache_event
                        expires_at = None
                        if ev.get("expires_at"):
                            expires_at = datetime.fromisoformat(ev["expires_at"])
                        await cache_event(
                            event_id=ev["id"],
                            event_type=layer,
                            payload_json=json.dumps(ev),
                            expires_at=expires_at,
                        )
                    except Exception:
                        pass
            await self.push(websocket, {"type": "snapshot", "data": events})
            logger.info("Sent snapshot for layer '%s': %d events", layer, len(events))
        except Exception as exc:
            logger.warning("Snapshot failed for layer '%s': %s", layer, exc)

    async def _db_snapshot(self, layer: str) -> list[dict]:
        """Query PostgreSQL for active (non-expired) events of a given type."""
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                text("""
                    SELECT
                        id::text, event_type, category, title, description,
                        ST_Y(location::geometry) AS lat,
                        ST_X(location::geometry) AS lng,
                        altitude_m, heading_deg, speed_kmh, severity,
                        source, source_url, source_id, metadata, trail,
                        created_at, expires_at
                    FROM events
                    WHERE event_type = :layer
                      AND (expires_at IS NULL OR expires_at > :now)
                    LIMIT 2000
                """),
                {"layer": layer, "now": now},
            )
            results = []
            for r in rows.mappings():
                results.append({
                    "id":          r["id"],
                    "event_type":  r["event_type"],
                    "category":    r["category"],
                    "title":       r["title"],
                    "description": r["description"],
                    "latitude":    float(r["lat"]) if r["lat"] is not None else None,
                    "longitude":   float(r["lng"]) if r["lng"] is not None else None,
                    "altitude_m":  r["altitude_m"],
                    "heading_deg": r["heading_deg"],
                    "speed_kmh":   r["speed_kmh"],
                    "severity":    r["severity"],
                    "source":      r["source"],
                    "source_url":  r["source_url"],
                    "source_id":   r["source_id"],
                    "metadata":    r["metadata"],
                    "trail":       r["trail"],
                    "created_at":  r["created_at"].isoformat() if r["created_at"] else None,
                    "expires_at":  r["expires_at"].isoformat() if r["expires_at"] else None,
                })
        return results

    # ── Redis listener (one per active layer) ─────────────────────────────────

    async def _redis_listener(self, layer: str) -> None:
        """
        Long-running task that reads from a Redis PubSub channel and forwards
        every message to all WebSocket clients subscribed to that layer.
        """
        logger.info("Redis listener started for layer '%s'", layer)
        try:
            async for message_json in subscribe_channel(layer):
                try:
                    data = json.loads(message_json)
                    await self.push_to_layer(
                        layer,
                        {"type": "event_update", "data": data},
                    )
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Malformed Redis message on layer '%s': %s", layer, exc
                    )
        except asyncio.CancelledError:
            logger.info("Redis listener cancelled for layer '%s'", layer)
        except Exception as exc:
            logger.exception(
                "Redis listener error on layer '%s': %s", layer, exc
            )

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    async def _heartbeat(self, websocket: WebSocket) -> None:
        """Send a ping every HEARTBEAT_INTERVAL seconds to keep the connection alive."""
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await self.push(websocket, {"type": "ping"})
        except asyncio.CancelledError:
            pass

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def subscriptions(self, websocket: WebSocket) -> set[str]:
        return self._connections.get(websocket, set()).copy()


manager = ConnectionManager()

