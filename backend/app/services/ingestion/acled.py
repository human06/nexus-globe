"""ACLED Conflict Data Ingestion — Story 3.2.

Polls the Armed Conflict Location & Event Data (ACLED) REST API hourly for
the past 7 days of global conflict events: battles, explosions, protests,
riots, violence against civilians, and strategic developments.

Requires ACLED_API_KEY + ACLED_EMAIL in environment (skip gracefully if absent).
API docs: https://acleddata.com/acleddatanew/wp-content/uploads/2021/11/ACLED_API-User-Guide_September-2021.pdf

Severity mapping:
  Battles (fatalities > 10)           → 5
  Explosions/Remote violence          → 4
  Violence against civilians          → 4
  Battles (fatalities ≤ 10)           → 3
  Riots with fatalities               → 3
  Riots without fatalities            → 2
  Protests                            → 2
  Strategic developments              → 1
  Bonus: fatalities > 50              → always 5

Events expire 30 days from the event date (conflict events have long relevance).
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)

ACLED_BASE_URL = "https://acleddata.com/api/acled/read"

# ACLED event_type → internal category
_EVENT_TYPE_MAP: dict[str, str] = {
    "Battles":                      "battle",
    "Explosions/Remote violence":   "explosion",
    "Violence against civilians":   "civilian_violence",
    "Protests":                     "protest",
    "Riots":                        "riot",
    "Strategic developments":       "strategic",
}

# Internal category → base severity (before fatality adjustment)
_SEVERITY_MAP: dict[str, int] = {
    "battle":            3,
    "explosion":         4,
    "civilian_violence": 4,
    "protest":           2,
    "riot":              2,
    "strategic":         1,
}


def _compute_severity(event_type: str, category: str, fatalities: int) -> int:
    """Compute severity 1-5 from ACLED event type and fatality count."""
    if fatalities > 50:
        return 5

    base = _SEVERITY_MAP.get(category, 1)

    if category == "battle":
        return 5 if fatalities > 10 else 3
    if category == "riot" and fatalities > 0:
        return 3
    return base


def _build_title(row: dict) -> str:
    """Build event title: notes excerpt or fallback to type-in-location."""
    notes: str = row.get("notes") or ""
    if notes.strip():
        return notes.strip()[:200]
    event_type: str = row.get("event_type") or "Conflict"
    location: str = row.get("location") or ""
    country: str = row.get("country") or ""
    parts = [p for p in [location, country] if p]
    location_str = ", ".join(parts) if parts else "unknown location"
    return f"{event_type} in {location_str}"


class ACLEDIngestionService(BaseIngestionService):
    """Ingests global conflict events from the ACLED API (hourly)."""

    source_name = "acled"
    poll_interval_seconds = 3600

    # ------------------------------------------------------------------ #
    # fetch_raw                                                            #
    # ------------------------------------------------------------------ #

    async def fetch_raw(self) -> Any:
        """Return the raw ACLED JSON payload, or None if unavailable."""
        api_key: str = settings.acled_api_key or ""
        email: str = settings.acled_email or ""

        if not api_key or not email:
            logger.warning(
                "[acled] ACLED_API_KEY / ACLED_EMAIL not set — skipping. "
                "Register at https://acleddata.com/register/ to enable conflict data."
            )
            return None

        # Last 7 days in YYYY-MM-DD format
        since_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

        params = {
            "key": api_key,
            "email": email,
            "event_date": since_date,
            "event_date_where": ">",
            "limit": "500",
            "_format": "json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(ACLED_BASE_URL, params=params)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("[acled] HTTP %s — %s", exc.response.status_code, exc.response.text[:300])
            return None
        except Exception as exc:  # noqa: BLE001
            logger.error("[acled] Fetch failed: %s: %s", type(exc).__name__, exc)
            return None

        if not payload.get("success") or payload.get("status") != 200:
            logger.warning("[acled] API returned non-success: %s", str(payload)[:300])
            return None

        rows = payload.get("data") or []
        logger.info("[acled] Fetched %d raw conflict events (since %s)", len(rows), since_date)
        return rows

    # ------------------------------------------------------------------ #
    # normalize                                                            #
    # ------------------------------------------------------------------ #

    async def normalize(self, raw: Any) -> list[dict]:
        """Convert ACLED rows → GlobeEvent dicts."""
        if not raw:
            return []

        events: list[dict] = []
        category_counts: Counter[str] = Counter()

        for row in raw:
            # ── coordinates ──────────────────────────────────────────────
            try:
                lat = float(row.get("latitude") or 0)
                lng = float(row.get("longitude") or 0)
            except (TypeError, ValueError):
                continue  # skip un-geocoded events

            if lat == 0.0 and lng == 0.0:
                continue  # ACLED sometimes emits 0,0 for unknown locations

            # ── classification ───────────────────────────────────────────
            acled_event_type: str = row.get("event_type") or "Unknown"
            category: str = _EVENT_TYPE_MAP.get(acled_event_type, "conflict")

            try:
                fatalities = int(row.get("fatalities") or 0)
            except (TypeError, ValueError):
                fatalities = 0

            severity = _compute_severity(acled_event_type, category, fatalities)

            # ── dates ────────────────────────────────────────────────────
            event_date_str: str = row.get("event_date") or ""
            try:
                event_dt = datetime.strptime(event_date_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except (ValueError, TypeError):
                event_dt = datetime.now(timezone.utc)

            expires_at = event_dt + timedelta(days=30)

            # ── title / description ──────────────────────────────────────
            title = _build_title(row)
            notes: str = row.get("notes") or ""

            # ── source identifiers ───────────────────────────────────────
            data_id: str = str(row.get("data_id") or row.get("event_id_cnty") or "")
            country: str = row.get("country") or ""
            location: str = row.get("location") or ""

            # ── assemble event ───────────────────────────────────────────
            event: dict = {
                "event_type": "conflict",
                "category": category,
                "title": title,
                "description": notes[:2000] if notes else title,
                "latitude": lat,
                "longitude": lng,
                "altitude_m": 0.0,
                "severity": severity,
                "source": "acled",
                "source_id": data_id,
                "source_url": (
                    f"https://acleddata.com/data-export-tool/"
                ),
                "expires_at": expires_at,
                "metadata": {
                    "acled_data_id": data_id,
                    "event_date": event_date_str,
                    "event_type": acled_event_type,
                    "sub_event_type": row.get("sub_event_type") or "",
                    "actor1": row.get("actor1") or "",
                    "actor2": row.get("actor2") or "",
                    "assoc_actor1": row.get("assoc_actor_1") or "",
                    "assoc_actor2": row.get("assoc_actor_2") or "",
                    "interaction": row.get("interaction") or "",
                    "fatalities": fatalities,
                    "country": country,
                    "admin1": row.get("admin1") or "",
                    "admin2": row.get("admin2") or "",
                    "admin3": row.get("admin3") or "",
                    "location": location,
                    "geo_precision": row.get("geo_precision") or "",
                    "source_scale": row.get("source_scale") or "",
                    "notes": notes[:500] if notes else "",
                    "tags": row.get("tags") or "",
                    "timestamp": row.get("timestamp") or "",
                },
            }
            events.append(event)
            category_counts[category] += 1

        # ── summary log ──────────────────────────────────────────────────
        total = len(events)
        summary_parts = [f"{cnt} {cat}" for cat, cnt in category_counts.most_common(6)]
        logger.info(
            "[acled] normalised %d conflict events (%s)",
            total,
            ", ".join(summary_parts) if summary_parts else "none",
        )
        return events
