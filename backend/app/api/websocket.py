"""WebSocket connection manager."""
from __future__ import annotations

import json
import logging
from collections import defaultdict

from fastapi.websockets import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections with per-layer pub/sub."""

    def __init__(self) -> None:
        # All active connections
        self.active_connections: dict[WebSocket, set[str]] = {}
        # Layer → set of subscribed WebSockets
        self._subscriptions: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections[websocket] = set()
        logger.info("WebSocket connected. Total: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        layers = self.active_connections.pop(websocket, set())
        for layer in layers:
            self._subscriptions[layer].discard(websocket)
        logger.info("WebSocket disconnected. Total: %d", len(self.active_connections))

    async def subscribe(self, websocket: WebSocket, layer: str) -> None:
        self.active_connections.setdefault(websocket, set()).add(layer)
        self._subscriptions[layer].add(websocket)
        logger.info("Client subscribed to layer '%s'", layer)

    async def unsubscribe(self, websocket: WebSocket, layer: str) -> None:
        self.active_connections.get(websocket, set()).discard(layer)
        self._subscriptions[layer].discard(websocket)
        logger.info("Client unsubscribed from layer '%s'", layer)

    async def broadcast(self, message: dict, layer: str | None = None) -> None:
        """Broadcast a message to all connections or only subscribers of a layer."""
        if layer:
            targets = self._subscriptions.get(layer, set()).copy()
        else:
            targets = set(self.active_connections.keys())

        payload = json.dumps(message)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
