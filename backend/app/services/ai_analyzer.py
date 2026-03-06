"""Claude AI integration for event enrichment."""
from __future__ import annotations

import logging
from typing import Any

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def enrich_event(event: dict[str, Any]) -> dict[str, Any]:
    """
    Use Claude to enrich an event with:
    - Severity score (1–5)
    - Concise description summary
    - Category tags
    - Estimated impact radius (km)

    TODO: implement full prompt + structured output parsing.

    Returns the event dict with additional keys added.
    """
    # TODO: implement Claude API call with structured output
    logger.debug("[ai_analyzer] enrich_event called — not yet implemented")
    return event


async def classify_severity(title: str, description: str) -> int:
    """
    Ask Claude to classify the severity 1–5 for an event title + description.

    TODO: implement Claude API call.
    """
    # TODO: implement severity classification prompt
    logger.debug("[ai_analyzer] classify_severity called — not yet implemented")
    return 1
