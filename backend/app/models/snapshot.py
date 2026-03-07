"""SQLAlchemy ORM model for the event_snapshots table (Story 3.5)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class EventSnapshot(Base):
    """
    Periodic compressed snapshot of all active events.

    Every 15 minutes the snapshot job captures the full set of active events
    (those not yet expired) and stores compressed summaries here.
    Retained for 7 days, then pruned.
    """

    __tablename__ = "event_snapshots"

    __table_args__ = (
        # Primary query: find nearest snapshot to a given timestamp
        Index("idx_snapshots_time", "snapshot_time", postgresql_using="btree"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    snapshot_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # {"flight": 4832, "news": 47, "satellite": 334, ...}
    layer_counts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Array of compressed event summaries:
    # [{"id": "...", "type": "flight", "lat": 51.5, "lng": -0.1,
    #   "sev": 3, "title": "BA123 over London"},  ...]
    events: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
