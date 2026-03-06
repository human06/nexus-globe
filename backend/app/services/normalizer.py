"""Event normalizer — converts source-specific dicts to a canonical schema."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def normalize_event(source: str, raw_event: dict[str, Any]) -> dict[str, Any] | None:
    """
    Normalise a raw event dict from any source into a GlobeEventCreate-compatible dict.

    TODO: implement per-source mapping logic.

    Returns None if the event should be discarded.
    """
    # TODO: implement source-specific normalization
    logger.debug("[normalizer] normalize_event called for source=%s", source)
    return raw_event
