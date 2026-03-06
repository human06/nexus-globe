"""Pydantic schemas for API request/response and WebSocket messages."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Event schemas ──────────────────────────────────────────────────────────────

class GlobeEventCreate(BaseModel):
    event_type: str
    category: str = ""
    title: str
    description: str = ""
    latitude: float
    longitude: float
    altitude_m: float | None = None
    heading_deg: float | None = None
    speed_kmh: float | None = None
    severity: int = Field(default=1, ge=1, le=5)
    source: str
    source_url: str | None = None
    source_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    trail: list[dict[str, Any]] | None = None
    expires_at: datetime | None = None


class GlobeEventResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    category: str
    title: str
    description: str
    latitude: float
    longitude: float
    altitude_m: float | None
    heading_deg: float | None
    speed_kmh: float | None
    severity: int
    source: str
    source_url: str | None
    source_id: str | None
    metadata: dict[str, Any]
    trail: list[dict[str, Any]] | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None

    model_config = {"from_attributes": True}


# ── WebSocket schemas ──────────────────────────────────────────────────────────

class WebSocketMessage(BaseModel):
    type: Literal["event_batch", "layer_status", "ping", "pong"]
    payload: Any = None


class LayerSubscription(BaseModel):
    action: Literal["subscribe", "unsubscribe"]
    layer: str
