"""SQLAlchemy ORM model for the events table."""
import uuid
from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Event(Base):
    __tablename__ = "events"

    # Indexes + constraints applied at table level
    __table_args__ = (
        # Composite index for the most common query pattern: type + time
        Index("ix_events_event_type_created_at", "event_type", "created_at"),
        # GIST spatial index on the PostGIS geography column
        Index("ix_events_location_gist", "location", postgresql_using="gist"),
        # Deduplication key: same source cannot produce two records with same source_id
        UniqueConstraint("source", "source_id", name="uq_events_source_source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # PostGIS geography point (WGS-84)
    location: Mapped[object] = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=True
    )

    altitude_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)

    severity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    source: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)

    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    trail: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
