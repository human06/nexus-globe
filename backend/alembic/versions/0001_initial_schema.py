"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-06 00:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import geoalchemy2
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable PostGIS extension if not already present
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("category", sa.String(64), nullable=False, server_default=""),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        # PostGIS GEOGRAPHY(POINT, 4326) — stores lon/lat on the sphere
        sa.Column(
            "location",
            geoalchemy2.types.Geography(geometry_type="POINT", srid=4326),
            nullable=True,
        ),
        sa.Column("altitude_m", sa.Float(), nullable=True),
        sa.Column("heading_deg", sa.Float(), nullable=True),
        sa.Column("speed_kmh", sa.Float(), nullable=True),
        sa.Column("severity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=True),
        sa.Column("source_id", sa.String(256), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("trail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Primary-key index is implicit; add the remaining indexes explicitly.

    # Simple indexes
    op.create_index("ix_events_event_type", "events", ["event_type"])
    op.create_index("ix_events_source_id", "events", ["source_id"])
    op.create_index("ix_events_expires_at", "events", ["expires_at"])

    # Composite index for the most common query pattern
    op.create_index(
        "ix_events_event_type_created_at",
        "events",
        ["event_type", "created_at"],
    )

    # GIST spatial index on the geography column for bbox queries
    op.create_index(
        "ix_events_location_gist",
        "events",
        ["location"],
        postgresql_using="gist",
    )

    # Unique constraint for deduplication — same (source, source_id) = same event
    op.create_unique_constraint(
        "uq_events_source_source_id",
        "events",
        ["source", "source_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_events_source_source_id", "events", type_="unique")
    op.drop_index("ix_events_location_gist", table_name="events")
    op.drop_index("ix_events_event_type_created_at", table_name="events")
    op.drop_index("ix_events_expires_at", table_name="events")
    op.drop_index("ix_events_source_id", table_name="events")
    op.drop_index("ix_events_event_type", table_name="events")
    op.drop_table("events")
