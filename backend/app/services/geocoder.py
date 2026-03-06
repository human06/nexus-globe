"""Async geocoding helper using geopy."""
from __future__ import annotations

import logging

from geopy.geocoders import Nominatim
from geopy.adapters import AioHTTPAdapter

logger = logging.getLogger(__name__)


async def geocode(location_string: str) -> tuple[float, float] | None:
    """
    Resolve a location string to (latitude, longitude).

    TODO: add caching layer (Redis) to avoid hammering Nominatim.
    Returns None if the location cannot be resolved.
    """
    # TODO: implement async geocoding with rate-limiting and caching
    logger.debug("[geocoder] geocode called for '%s'", location_string)
    try:
        async with Nominatim(
            user_agent="nexus-globe",
            adapter_factory=AioHTTPAdapter,
        ) as geolocator:
            location = await geolocator.geocode(location_string)  # type: ignore[attr-defined]
            if location:
                return (location.latitude, location.longitude)
    except Exception as exc:
        logger.warning("[geocoder] Failed to geocode '%s': %s", location_string, exc)
    return None
