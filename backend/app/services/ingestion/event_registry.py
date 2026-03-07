"""Event Registry Ingestion — Story 2.2 (Tier 2 — Smart).

Polls the Event Registry article API every 120 seconds (to respect the
free-tier 200 req/day limit) and returns pre-clustered, pre-geocoded
articles that complement the Tier-1 RSS fast feed.

Strengths over Tier 1 (RSS):
  - Coordinates already attached to most articles (no AI geocoding needed)
  - Category + concept metadata (politics, sports, technology, etc.)
  - Cluster leadership: multiple articles about the same event are grouped,
    so we only ingest the cluster representative — no self-dedup required.
  - Cross-source dedup with existing RSS events is handled by
    ``source_id`` (event URI) through the base upsert pipeline.

API shape (snippet):
    {
      "articles": {
        "results": [
          {
            "uri": "8234567",
            "title": "...",
            "body": "...",
            "source": { "uri": "reuters.com" },
            "location": { "lat": 48.8566, "long": 2.3522, "label": "Paris" },
            "categories": [{ "uri": "news/Politics" }],
            "concepts": [{ "label": "Emmanuel Macron", "type": "person" }],
            "sentiment": -0.3,
            "relevance": 85,
            "dateTimePub": "2024-01-15T12:30:00Z"
          }
        ]
      }
    }

Missing API key → service logs a warning and returns 0 events every cycle;
nothing else is affected.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)

ER_ARTICLE_ENDPOINT = "https://eventregistry.org/api/v1/article/getArticles"

# Map Event Registry category URI prefixes → our internal category labels
_ER_CATEGORY_MAP: dict[str, str] = {
    "news/Politics":             "politics",
    "news/Conflict,_War_And_Peace": "conflict",
    "news/Disaster,_Accident_And_Emergency_Incident": "disaster",
    "news/Economy,_Business_And_Finance": "economy",
    "news/Health":               "health",
    "news/Science_And_Technology": "technology",
    "news/Environment":          "environment",
    "news/Arts,_Culture,_Entertainment_And_Media": "culture",
    "news/Sport":                "sports",
    "news/Society":              "society",
    "news/Weather":              "weather",
    "news/Crime,_Law_And_Justice": "crime",
    "news/Human_Interest":       "human_interest",
    "news/Education":            "education",
    "news/Religion_And_Belief":  "religion",
    "news/Labour":               "labour",
}


def _map_category(categories: list[dict]) -> str:
    """Return the best-matching internal category label, else 'news'."""
    for cat in categories:
        uri = cat.get("uri", "")
        for prefix, label in _ER_CATEGORY_MAP.items():
            if uri.startswith(prefix):
                return label
    return "news"


def _relevance_to_severity(relevance: float | int | None) -> int:
    """Convert Event Registry article relevance (0-100) to severity (1-5)."""
    if relevance is None:
        return 3
    if relevance >= 80:
        return 5
    if relevance >= 60:
        return 4
    if relevance >= 40:
        return 3
    if relevance >= 20:
        return 2
    return 1


def _parse_date(dt_str: str | None) -> datetime:
    """Parse an ISO-8601 datetime string, falling back to now on failure."""
    if not dt_str:
        return datetime.now(timezone.utc)
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(dt_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


class EventRegistryService(BaseIngestionService):
    """Tier-2 smart news source — Event Registry pre-clustered articles."""

    source_name = "event_registry"
    poll_interval_seconds = 120

    # ---------------------------------------------------------------------------
    # BaseIngestionService interface
    # ---------------------------------------------------------------------------

    async def fetch_raw(self) -> Any:
        """
        Return raw API response dict, or None when the API key is absent /
        the call fails.
        """
        if not settings.event_registry_api_key:
            logger.warning(
                "[event_registry] EVENT_REGISTRY_API_KEY not set — skipping."
                " Set it in .env to enable Tier-2 news."
            )
            return None

        # Look back 1 hour for recent articles
        from datetime import timedelta
        date_start = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d")

        params = {
            "apiKey":                    settings.event_registry_api_key,
            "resultType":                "articles",
            "articlesSortBy":            "date",
            "articlesSortByAsc":         False,
            "articlesCount":             50,
            "lang":                      "eng",
            "dateStart":                 date_start,
            "dataType":                  ["news"],
            "includeArticleLocation":    True,
            "includeArticleConcepts":    True,
            "includeArticleCategories":  True,
            "includeArticleSentiment":   True,
            "includeSourceImportanceRank": True,
        }

        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    ER_ARTICLE_ENDPOINT,
                    json=params,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                elapsed = time.monotonic() - t0
                total = data.get("articles", {}).get("totalResults", "?")
                logger.info(
                    "[event_registry] API response: %s total results in %.1fs",
                    total, elapsed,
                )
                return data
        except httpx.HTTPStatusError as exc:
            logger.warning("[event_registry] HTTP %s — %s", exc.response.status_code, exc)
        except Exception as exc:
            logger.warning("[event_registry] fetch failed: %s", exc)
        return None

    async def normalize(self, raw: Any) -> list[dict]:
        """Convert Event Registry API response → list of GlobeEvent dicts."""
        if raw is None:
            return []

        articles = raw.get("articles", {}).get("results", [])
        if not articles:
            logger.info("[event_registry] No articles in response")
            return []

        events: list[dict] = []
        skipped_no_title = 0

        for article in articles:
            title = (article.get("title") or "").strip()
            if not title:
                skipped_no_title += 1
                continue

            # --- Coordinates (ER provides them for most articles) ---
            loc     = article.get("location") or {}
            lat     = loc.get("lat")  or loc.get("latitude")
            lng     = loc.get("long") or loc.get("longitude")
            loc_label = loc.get("label", "")
            needs_geocoding = lat is None or lng is None

            # --- Category ---
            categories_raw = article.get("categories") or []
            category = _map_category(categories_raw)

            # --- Concepts (people, orgs, locations) ---
            concepts = article.get("concepts") or []
            people   = [c["label"]["eng"] for c in concepts
                        if c.get("type") == "person" and "eng" in c.get("label", {})]
            orgs     = [c["label"]["eng"] for c in concepts
                        if c.get("type") == "org" and "eng" in c.get("label", {})]
            locations = [c["label"]["eng"] for c in concepts
                         if c.get("type") == "place" and "eng" in c.get("label", {})]

            # --- Severity from relevance ---
            relevance = article.get("relevance")
            severity  = _relevance_to_severity(relevance)

            # --- Timestamps ---
            published = _parse_date(article.get("dateTimePub") or article.get("date"))

            # --- Source info ---
            source_obj  = article.get("source") or {}
            source_domain = source_obj.get("uri", "")
            article_uri   = article.get("uri", "")

            # Body excerpt (500 chars)
            body = (article.get("body") or article.get("description") or "").strip()[:500]

            events.append({
                # Core GlobeEvent fields
                "event_type":  "news",
                "category":    category,
                "title":       title[:200],
                "description": body,
                "latitude":    float(lat) if lat is not None else None,
                "longitude":   float(lng) if lng is not None else None,
                "severity":    severity,
                "source":      "event_registry",
                "source_id":   article_uri or None,
                "source_url":  article.get("url"),
                "expires_at":  published + timedelta(hours=24),
                "metadata": {
                    "er_event_uri":              article_uri,
                    "er_categories":             [c.get("uri", "") for c in categories_raw],
                    "er_concepts": {
                        "people":    people[:10],
                        "orgs":      orgs[:10],
                        "locations": locations[:10],
                    },
                    "article_count_in_cluster":  article.get("eventUri") and 1,
                    "sentiment":                 article.get("sentiment"),
                    "source_domain":             source_domain,
                    "location_label":            loc_label,
                    "relevance":                 relevance,
                    "needs_geocoding":           needs_geocoding,
                    "published_date":            published.isoformat(),
                },
            })

        # Summarise by category
        cat_counts: dict[str, int] = {}
        for ev in events:
            cat_counts[ev["category"]] = cat_counts.get(ev["category"], 0) + 1
        breakdown = ", ".join(f"{c} {k}" for k, c in sorted(cat_counts.items(), key=lambda x: -x[1]))

        logger.info(
            "EventRegistry: ingested %d events (%s) — %d skipped (no title)",
            len(events), breakdown or "none", skipped_no_title,
        )
        return events
