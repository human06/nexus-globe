"""OpenRouter AI Event Analyzer — Story 2.8.

Two-job pipeline, priority-ordered:
  1. **Geocoding** — RSS/GDELT articles that arrived with no lat/lng get a
     location extracted from their headline + description.
  2. **Enrichment** — News events get a structured analysis: summary, entities,
     tags, refined severity, and related context.

Model is configurable via ``AI_MODEL`` env var; auto-falls back to
``AI_MODEL_FALLBACK`` on any error.  Gracefully does nothing when no API key
is set.

Rate limiting is a simple rolling-window counter (max N requests / minute).
Results are cached by source_id to avoid re-analyzing the same article.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime, date, timezone
from typing import Any

import httpx
from sqlalchemy import text

from app.config import settings
from app.db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

_NEEDS_GEOCODING_SQL = text("""
    SELECT id::text, title, description, source, source_id
    FROM events
    WHERE event_type = 'news'
      AND location IS NULL
      AND (metadata->>'needs_geocoding')::boolean IS NOT FALSE
      AND (metadata->>'ai_geocoded') IS NULL
      AND expires_at > NOW()
    ORDER BY created_at DESC
    LIMIT :limit
""")

_NEEDS_ENRICHMENT_SQL = text("""
    SELECT id::text, title, description, source, source_id,
           ST_Y(location::geometry) AS lat,
           ST_X(location::geometry) AS lng
    FROM events
    WHERE event_type = 'news'
      AND location IS NOT NULL
      AND (metadata->>'ai_enriched') IS NULL
      AND expires_at > NOW()
    ORDER BY created_at DESC
    LIMIT :limit
""")

_UPDATE_GEO_SQL = text("""
    UPDATE events
    SET location    = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
        metadata    = metadata || cast(:patch as jsonb),
        updated_at  = NOW()
    WHERE id = cast(:event_id as uuid)
""")

_UPDATE_ENRICH_SQL = text("""
    UPDATE events
    SET severity   = GREATEST(severity, :severity),
        metadata   = metadata || cast(:patch as jsonb),
        updated_at = NOW()
    WHERE id = cast(:event_id as uuid)
""")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_GEO_SYSTEM = "You are a geolocation expert. Return ONLY valid JSON, no commentary."

_GEO_USER = (
    "Extract the primary geographic location from this news headline.\n"
    "Title: {title}\n"
    "Description: {description}\n\n"
    'Return JSON: {{"latitude": float_or_null, "longitude": float_or_null, '
    '"location_name": "string", "confidence": 0.0_to_1.0}}\n'
    "If no location can be determined, return "
    '{{"latitude": null, "longitude": null, "location_name": "", "confidence": 0}}'
)

_ENRICH_SYSTEM = (
    "You are an expert OSINT analyst. Analyze news events and return ONLY valid JSON."
)

_ENRICH_USER = (
    "Analyze this news event:\n"
    "Title: {title}\n"
    "Source: {source} | Location: {lat}, {lng}\n"
    "Description: {description}\n\n"
    "Return JSON:\n"
    '{{"summary": "2-3 sentence summary", '
    '"category": "one of: conflict/disaster/politics/economy/crime/protest/humanitarian/other", '
    '"severity": 1_to_5_int, '
    '"entities": {{"people": ["..."], "countries": ["..."], "organizations": ["..."]}}, '
    '"tags": ["tag1", "tag2"], '
    '"related_context": "brief background context"}}'
)


# ---------------------------------------------------------------------------
# AIAnalyzer
# ---------------------------------------------------------------------------

class AIAnalyzer:
    """AI event analysis via OpenRouter (OpenAI-compatible API)."""

    def __init__(self) -> None:
        self.base_url = settings.openrouter_base_url
        self.api_key  = settings.openrouter_api_key
        self.model    = settings.ai_model
        self.fallback = settings.ai_model_fallback
        self.max_tokens   = settings.ai_max_tokens
        self.temperature  = settings.ai_temperature
        self.max_rpm      = settings.ai_max_requests_per_minute

        # Rolling-window rate limiter (monotonic timestamps of recent calls)
        self._req_times: deque[float] = deque()

        # Daily stats (reset when the date changes)
        self._stats_date: date = datetime.now(timezone.utc).date()
        self._stats: dict[str, Any] = self._fresh_stats()

        # In-memory cache: already-analyzed source_ids (prevent re-run)
        self._geocoded_ids:  set[str] = set()
        self._enriched_ids:  set[str] = set()

    # -----------------------------------------------------------------------
    # Properties
    # -----------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def get_status(self) -> dict:
        self._maybe_reset_stats()
        avg_latency = (
            round(self._stats["total_latency_ms"] / self._stats["request_count"])
            if self._stats["request_count"] > 0 else 0
        )
        return {
            "enabled":              self.enabled,
            "provider":             "openrouter",
            "primary_model":        self.model,
            "fallback_model":       self.fallback,
            "events_enriched_today":self._stats["events_enriched"],
            "events_geocoded_today":self._stats["events_geocoded"],
            "avg_latency_ms":       avg_latency,
            "total_tokens_today":   self._stats["total_tokens"],
        }

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def geocode_event(self, event: dict) -> dict:
        """
        Attempt to geocode *event* using the AI.

        Mutates and returns the dict.  On any failure returns event unchanged.
        """
        if not self.enabled:
            return event

        title       = event.get("title", "")
        description = event.get("description", "")
        messages = [
            {"role": "system", "content": _GEO_SYSTEM},
            {"role": "user",   "content": _GEO_USER.format(
                title=title[:300], description=description[:500]
            )},
        ]
        try:
            t0   = time.monotonic()
            resp = await self._rate_limited_call(messages)
            ms   = round((time.monotonic() - t0) * 1000)
            geo  = self._extract_json(resp)
            tokens = (resp.get("usage") or {}).get("total_tokens", 0)
            model_used = (resp.get("model") or self.model)

            lat = geo.get("latitude")
            lng = geo.get("longitude")
            confidence = float(geo.get("confidence", 0))

            if lat is not None and lng is not None and confidence >= 0.5:
                event["latitude"]  = float(lat)
                event["longitude"] = float(lng)
                meta = event.setdefault("metadata", {})
                meta["ai_geocoded"]          = True
                meta["needs_geocoding"]      = False
                meta["location_name"]        = geo.get("location_name", "")
                meta["geocode_confidence"]   = confidence
                meta["ai_model"]             = model_used

                self._stats["events_geocoded"] += 1
                self._stats["total_tokens"]    += tokens
                self._stats["total_latency_ms"] += ms
                self._stats["request_count"]   += 1
                logger.debug(
                    "[ai] geocoded '%s' → %.4f, %.4f (conf %.2f) [%s, %d ms, %d tok]",
                    title[:60], lat, lng, confidence, model_used, ms, tokens,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ai] geocode_event failed for '%s': %s", title[:60], exc)

        return event

    async def enrich_event(self, event: dict) -> dict:
        """
        Full AI enrichment: summary, category, severity, entities, tags.

        Mutates and returns the dict.  On any failure returns event unchanged.
        """
        if not self.enabled:
            return event

        title       = event.get("title", "")
        description = event.get("description", "")
        source      = event.get("source", "")
        lat         = event.get("latitude")  or 0.0
        lng         = event.get("longitude") or 0.0
        messages = [
            {"role": "system", "content": _ENRICH_SYSTEM},
            {"role": "user",   "content": _ENRICH_USER.format(
                title=title[:300], source=source,
                lat=f"{lat:.4f}", lng=f"{lng:.4f}",
                description=description[:500],
            )},
        ]
        try:
            t0   = time.monotonic()
            resp = await self._rate_limited_call(messages)
            ms   = round((time.monotonic() - t0) * 1000)
            enriched = self._extract_json(resp)
            tokens = (resp.get("usage") or {}).get("total_tokens", 0)
            model_used = (resp.get("model") or self.model)

            meta = event.setdefault("metadata", {})
            meta["ai_enriched"]      = True
            meta["ai_summary"]       = enriched.get("summary", "")
            meta["ai_category"]      = enriched.get("category", "")
            meta["ai_severity"]      = enriched.get("severity")
            meta["ai_entities"]      = enriched.get("entities", {})
            meta["ai_tags"]          = enriched.get("tags", [])
            meta["ai_context"]       = enriched.get("related_context", "")
            meta["ai_model"]         = model_used

            # Upgrade severity if AI thinks it's higher
            ai_sev = enriched.get("severity")
            if isinstance(ai_sev, int) and 1 <= ai_sev <= 5:
                event["severity"] = max(event.get("severity", 1), ai_sev)

            self._stats["events_enriched"]  += 1
            self._stats["total_tokens"]     += tokens
            self._stats["total_latency_ms"] += ms
            self._stats["request_count"]    += 1
            logger.debug(
                "[ai] enriched '%s' sev=%s [%s, %d ms, %d tok]",
                title[:60], event.get("severity"), model_used, ms, tokens,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ai] enrich_event failed for '%s': %s", title[:60], exc)

        return event

    async def enrich_batch(self, events: list[dict]) -> list[dict]:
        """
        Process a batch of events (≤ 5): geocoding first, then enrichment.

        Returns the mutated list.
        """
        BATCH_LIMIT = 5
        batch = events[:BATCH_LIMIT]

        # Phase 1: Geocoding pass
        for ev in batch:
            if ev.get("metadata", {}).get("needs_geocoding") or ev.get("latitude") is None:
                await self.geocode_event(ev)

        # Phase 2: Enrichment pass
        for ev in batch:
            meta = ev.get("metadata") or {}
            if not meta.get("ai_enriched") and ev.get("latitude") is not None:
                await self.enrich_event(ev)

        return batch

    async def run_enrichment_cycle(self, geocode_limit: int = 10, enrich_limit: int = 10) -> dict:
        """
        Pull pending events from DB, geocode / enrich, and write results back.

        Designed to be called by the scheduler every 60-120 s.
        Returns stats dict.
        """
        if not self.enabled:
            return {"skipped": True, "reason": "no API key"}

        t0 = time.monotonic()
        geocoded = enriched = 0

        # ── Geocoding pass ─────────────────────────────────────────── #
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                _NEEDS_GEOCODING_SQL, {"limit": geocode_limit}
            )
            rows = result.mappings().all()

        for row in rows:
            source_id = str(row["source_id"] or row["id"])
            if source_id in self._geocoded_ids:
                continue
            event_stub = {
                "title":       row["title"],
                "description": row["description"],
                "source":      row["source"],
            }
            updated = await self.geocode_event(event_stub)
            if updated.get("latitude") is not None:
                patch = {
                    k: v for k, v in (updated.get("metadata") or {}).items()
                    if k.startswith("ai_") or k in ("needs_geocoding", "location_name", "geocode_confidence")
                }
                async with AsyncSessionLocal() as write_session:
                    async with write_session.begin():
                        await write_session.execute(
                            _UPDATE_GEO_SQL,
                            {
                                "event_id": row["id"],
                                "lat":      updated["latitude"],
                                "lng":      updated["longitude"],
                                "patch":    json.dumps(patch),
                            },
                        )
                self._geocoded_ids.add(source_id)
                geocoded += 1

        # ── Enrichment pass ────────────────────────────────────────── #
        async with AsyncSessionLocal() as session2:
            result2 = await session2.execute(
                _NEEDS_ENRICHMENT_SQL, {"limit": enrich_limit}
            )
            rows2 = result2.mappings().all()

        for row in rows2:
            source_id = str(row["source_id"] or row["id"])
            if source_id in self._enriched_ids:
                continue
            event_stub = {
                "title":       row["title"],
                "description": row["description"],
                "source":      row["source"],
                "latitude":    float(row["lat"]) if row["lat"] else None,
                "longitude":   float(row["lng"]) if row["lng"] else None,
                "severity":    1,
            }
            updated = await self.enrich_event(event_stub)
            if (updated.get("metadata") or {}).get("ai_enriched"):
                meta = updated.get("metadata") or {}
                patch = {
                    k: v for k, v in meta.items()
                    if k.startswith("ai_")
                }
                async with AsyncSessionLocal() as write_session2:
                    async with write_session2.begin():
                        await write_session2.execute(
                            _UPDATE_ENRICH_SQL,
                            {
                                "event_id": row["id"],
                                "severity": updated.get("severity", 1),
                                "patch":    json.dumps(patch),
                            },
                        )
                self._enriched_ids.add(source_id)
                enriched += 1

        elapsed = round((time.monotonic() - t0) * 1000)
        if geocoded or enriched:
            logger.info(
                "AI [%s]: geocoded %d + enriched %d events in %.1fs",
                self.model, geocoded, enriched, elapsed / 1000,
            )
        return {"geocoded": geocoded, "enriched": enriched, "elapsed_ms": elapsed}

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _rate_limited_call(
        self, messages: list[dict], model: str | None = None
    ) -> dict:
        """Call the model with rolling-window rate limiting + fallback."""
        await self._wait_for_rate_limit()
        try:
            return await self._call_model(messages, model or self.model)
        except Exception as primary_exc:
            logger.warning(
                "[ai] Primary model %s failed (%s), retrying with %s",
                model or self.model, primary_exc, self.fallback,
            )
            try:
                return await self._call_model(messages, self.fallback)
            except Exception as fb_exc:
                raise RuntimeError(
                    f"Both models failed — primary: {primary_exc}; fallback: {fb_exc}"
                ) from fb_exc

    async def _call_model(self, messages: list[dict], model: str) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type":  "application/json",
                    "HTTP-Referer":  "https://nexus-globe.app",
                    "X-Title":       "NEXUS GLOBE OSINT",
                },
                json={
                    "model":           model,
                    "messages":        messages,
                    "max_tokens":      self.max_tokens,
                    "temperature":     self.temperature,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def _wait_for_rate_limit(self) -> None:
        """Block (by sleeping) until within the configured RPM budget."""
        now = time.monotonic()
        window = 60.0
        while self._req_times and now - self._req_times[0] > window:
            self._req_times.popleft()
        if len(self._req_times) >= self.max_rpm:
            wait = window - (now - self._req_times[0]) + 0.05
            await asyncio.sleep(wait)
        self._req_times.append(time.monotonic())

    @staticmethod
    def _extract_json(response: dict) -> dict:
        """Extract and parse the JSON payload from an OpenAI-compatible response."""
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "{}")
        )
        # Strip markdown code fences if any
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected JSON object, got {type(parsed)}")
        return parsed

    def _maybe_reset_stats(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._stats_date:
            self._stats_date = today
            self._stats = self._fresh_stats()

    @staticmethod
    def _fresh_stats() -> dict:
        return {
            "events_geocoded":  0,
            "events_enriched":  0,
            "total_tokens":     0,
            "total_latency_ms": 0,
            "request_count":    0,
        }


# ---------------------------------------------------------------------------
# Module-level singleton (used by scheduler + API)
# ---------------------------------------------------------------------------

_analyzer: AIAnalyzer | None = None


def get_analyzer() -> AIAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = AIAnalyzer()
    return _analyzer

