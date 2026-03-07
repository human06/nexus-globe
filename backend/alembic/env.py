"""Alembic environment — async SQLAlchemy + PostGIS aware."""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ── Make sure the backend app package is importable ───────────────────────────
# When Alembic runs from backend/, the app package must be on the path.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import settings  # noqa: E402
from app.db.database import Base  # noqa: E402
import app.models.event     # noqa: E402, F401  — populate Base.metadata
import app.models.snapshot  # noqa: E402, F401  — event_snapshots table

# ── Alembic Config object ─────────────────────────────────────────────────────
config = context.config

# Inject the real DB URL from settings (overrides the placeholder in alembic.ini)
config.set_main_option("sqlalchemy.url", settings.database_url)

# Configure Python logging from the ini file if present
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for autogenerate support
target_metadata = Base.metadata


# ── Offline migrations (generate SQL without a live connection) ───────────────
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Required for PostGIS / geoalchemy2 types
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (apply against a live async connection) ─────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        # Compare server defaults so Alembic doesn't always regenerate them
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ── Entry point ───────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
