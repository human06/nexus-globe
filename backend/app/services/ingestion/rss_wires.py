"""RSS Wire Service Ingestion — Story 2.1 (Tier 1 — Fast).

Polls major wire service RSS/Atom feeds every 30 seconds and normalises
articles into GlobeEvents flagged with ``needs_geocoding: true`` so the
AI enricher (Story 2.8) can add lat/lng coordinates.

Sources (all free, no auth required):
  - Reuters World  — https://www.reutersagency.com/feed/?best-topics=world
  - AP Top News    — https://rsshub.app/apnews/topics/apf-topnews
  - BBC World      — https://feeds.bbci.co.uk/news/world/rss.xml
  - Al Jazeera     — https://www.aljazeera.com/xml/rss/all.xml
  - France24       — https://www.france24.com/en/rss
  - DW (Deutsche Welle) — https://rss.dw.com/rdf/rss-en-world

Dedup strategy:
  - Primary (same-feed): SHA-256 of the article link used as ``source_id``
  - Cross-feed (same story on Reuters + BBC): title fuzzy-match > 80 %
    within a 2-hour window → keep earliest, record others in
    ``metadata.also_reported_by``.

Pipeline integration:
  - Events land in the ``upsert_events`` pipeline from the base class.
  - Events with ``metadata.needs_geocoding = True`` are queued for the
    AI Analyzer (Story 2.8) which will back-fill lat/lng and re-broadcast.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from hashlib import sha256
from typing import Any

import feedparser  # type: ignore[import-untyped]
import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feed registry — name → URL
# ---------------------------------------------------------------------------
RSS_FEEDS: dict[str, str] = {
    "reuters":   "https://www.reutersagency.com/feed/?best-topics=world",
    "ap":        "https://rsshub.app/apnews/topics/apf-topnews",
    "bbc":       "https://feeds.bbci.co.uk/news/world/rss.xml",
    "aljazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "france24":  "https://www.france24.com/en/rss",
    "dw":        "https://rss.dw.com/rdf/rss-en-world",
}

# How similar two titles must be (0–1) to count as the same story
_TITLE_SIMILARITY_THRESHOLD = 0.80

# Cross-feed dedup window in hours — only compare articles newer than this
_DEDUP_WINDOW_HOURS = 2


def _source_id(link: str) -> str:
    """Stable 16-char source_id derived from the article's canonical URL."""
    return sha256(link.encode()).hexdigest()[:16]


def _titles_similar(t1: str, t2: str, threshold: float = _TITLE_SIMILARITY_THRESHOLD) -> bool:
    """Return True when t1 and t2 are likely the same headline."""
    return SequenceMatcher(
        None, t1.lower().strip(), t2.lower().strip()
    ).ratio() >= threshold


def _parse_published(entry: Any) -> datetime:
    """Parse the publication timestamp from an RSS entry, fall back to now."""
    ts = entry.get("published_parsed") or entry.get("updated_parsed")
    if ts:
        try:
            import time as _time
            return datetime.fromtimestamp(_time.mktime(ts), tz=timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


class RSSWireService(BaseIngestionService):
    """Tier-1 fast news source — RSS/Atom wire feeds, no API key required."""

    source_name = "rss_wires"
    poll_interval_seconds = 30

    # ---------------------------------------------------------------------------
    # BaseIngestionService interface
    # ---------------------------------------------------------------------------

    async def fetch_raw(self) -> dict[str, list]:
        """
        Fetch all feeds concurrently using httpx and parse with feedparser.

        Returns ``{feed_name: [entry, ...], ...}`` even when individual feeds
        fail — failures are logged and the feed is silently skipped.
        """
        results: dict[str, list] = {}

        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "NexusGlobe/1.0 (news-intelligence-dashboard)"},
        ) as client:
            tasks = {
                name: asyncio.create_task(self._fetch_one(client, name, url))
                for name, url in RSS_FEEDS.items()
            }
            for name, task in tasks.items():
                try:
                    entries = await task
                    results[name] = entries
                except Exception as exc:
                    logger.warning("[rss_wires] Feed '%s' failed: %s", name, exc)
                    results[name] = []

        total = sum(len(v) for v in results.values())
        counts = ", ".join(f"{len(v)} {k}" for k, v in results.items() if v)
        logger.info("[rss_wires] Fetched %d articles (%s)", total, counts or "none")
        return results

    async def _fetch_one(
        self, client: httpx.AsyncClient, name: str, url: str
    ) -> list:
        """Fetch a single feed and return its parsed entries (may be empty)."""
        resp = await client.get(url)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)
        return parsed.entries or []

    async def normalize(self, raw: dict[str, list]) -> list[dict]:
        """
        Convert raw feed entries → event dicts compatible with ``upsert_events``.

        Steps
        -----
        1. Convert every entry from every feed into a candidate event dict.
        2. Apply in-batch cross-feed dedup: if two entries from different feeds
           share a similar title (within ``_DEDUP_WINDOW_HOURS``), keep the
           earliest and record the others in ``metadata.also_reported_by``.
        3. Return the deduplicated list.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=_DEDUP_WINDOW_HOURS)
        candidates: list[dict] = []

        for feed_name, entries in raw.items():
            for entry in entries:
                link = entry.get("link") or ""
                if not link:
                    continue  # skip entries with no canonical URL

                published = _parse_published(entry)
                title = (entry.get("title") or "").strip()[:200]
                if not title:
                    continue

                description = (
                    entry.get("summary") or entry.get("description") or ""
                ).strip()[:500]

                # Strip any HTML tags that slip through (simple approach)
                import re as _re
                description = _re.sub(r"<[^>]+>", " ", description).strip()[:500]

                categories = [
                    t.get("term", "").strip()
                    for t in entry.get("tags", [])
                    if t.get("term")
                ]

                candidates.append({
                    # Core GlobeEvent fields
                    "event_type":  "news",
                    "category":    "breaking",
                    "title":       title,
                    "description": description,
                    # Coordinates are null — flagged for AI geocoding
                    "latitude":    None,
                    "longitude":   None,
                    "severity":    3,
                    "source":      feed_name,
                    "source_id":   _source_id(link),
                    "source_url":  link,
                    "expires_at":  published + timedelta(hours=24),
                    "metadata": {
                        "feed_source":     feed_name,
                        "published_date":  published.isoformat(),
                        "categories":      categories,
                        "author":          entry.get("author", ""),
                        "needs_geocoding": True,
                        "also_reported_by": [],
                    },
                    # Internal helpers (not persisted — used for in-batch dedup)
                    "_published":  published,
                    "_title_lc":   title.lower().strip(),
                })

        # Cross-feed deduplication within this batch
        deduped = self._cross_feed_dedup(candidates, cutoff)

        # Remove internal helper keys before returning
        for ev in deduped:
            ev.pop("_published", None)
            ev.pop("_title_lc", None)

        ingested_count = len(deduped)
        merged_count   = len(candidates) - ingested_count
        source_counts  = {}
        for ev in deduped:
            source_counts[ev["source"]] = source_counts.get(ev["source"], 0) + 1
        breakdown = ", ".join(f"{c} {s}" for s, c in sorted(source_counts.items()))
        logger.info(
            "RSS Wires: ingested %d articles (%s) — %d cross-feed duplicates merged",
            ingested_count, breakdown or "none", merged_count,
        )
        return deduped

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _cross_feed_dedup(
        self, candidates: list[dict], cutoff: datetime
    ) -> list[dict]:
        """
        Merge candidates that look like the same story from multiple feeds.

        Algorithm (O(n²) but n is small, < 300 per cycle):
        1. Sort by ``_published`` ascending so the oldest becomes primary.
        2. For each candidate, if it hasn't already been absorbed into an earlier
           event, compare its title to all subsequent candidates within the
           dedup window.  When similarity >= threshold, absorb the later one into
           ``metadata.also_reported_by`` of the earlier one.
        """
        # Sort oldest-first so the earliest version survives
        sorted_cands = sorted(candidates, key=lambda e: e["_published"])

        absorbed: set[int] = set()
        for i, primary in enumerate(sorted_cands):
            if i in absorbed:
                continue
            # Only dedup articles within the time window
            if primary["_published"] < cutoff:
                continue
            for j in range(i + 1, len(sorted_cands)):
                if j in absorbed:
                    continue
                other = sorted_cands[j]
                if other["source"] == primary["source"]:
                    continue  # same-feed dedup is handled by source_id
                if abs((other["_published"] - primary["_published"]).total_seconds()) > _DEDUP_WINDOW_HOURS * 3600:
                    break  # list is sorted; no point checking further
                if _titles_similar(primary["_title_lc"], other["_title_lc"]):
                    primary["metadata"]["also_reported_by"].append(other["source"])
                    absorbed.add(j)

        return [ev for idx, ev in enumerate(sorted_cands) if idx not in absorbed]
