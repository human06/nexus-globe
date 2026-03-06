"""Event deduplication helpers."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def deduplicate_events(
    incoming: list[dict[str, Any]],
    existing_source_ids: set[str],
) -> list[dict[str, Any]]:
    """
    Remove events whose source_id is already present in the database.

    TODO: also add proximity/text-similarity deduplication for sources
    that don't provide stable IDs.

    Returns the subset of `incoming` that are new.
    """
    # TODO: implement full deduplication logic
    logger.debug(
        "[dedup] %d incoming, %d existing — filtering duplicates",
        len(incoming),
        len(existing_source_ids),
    )
    unique: list[dict[str, Any]] = []
    for ev in incoming:
        sid = ev.get("source_id")
        if sid and sid in existing_source_ids:
            continue
        unique.append(ev)
    return unique
