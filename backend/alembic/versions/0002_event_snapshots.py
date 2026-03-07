"""add event_snapshots table

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-07 00:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "snapshot_time",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "event_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "layer_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "events",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # Primary descending index for fast nearest-snapshot lookups
    op.create_index(
        "idx_snapshots_time",
        "event_snapshots",
        ["snapshot_time"],
        postgresql_ops={"snapshot_time": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("idx_snapshots_time", table_name="event_snapshots")
    op.drop_table("event_snapshots")
