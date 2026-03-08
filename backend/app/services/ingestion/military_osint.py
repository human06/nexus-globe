"""Military OSINT Aggregator — Story 3.3.

Supplements ACLED with near-real-time open-source military intelligence by
aggregating reports from multiple free public feeds:

  * ReliefWeb API   — UN OCHA humanitarian crisis reports (free, no key)
  * Liveuamap RSS   — conflict map news feed (public)

All events are marked ``verification_status: "unverified"`` because OSINT
sources vary in reliability.  When ACLED later confirms the same event the
conflict cross-reference dedup in ``dedup.py`` flips the status to
``"confirmed"``.

Poll interval: 300 seconds (5 minutes).
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source definitions
# ---------------------------------------------------------------------------

RELIEFWEB_URL = (
    "https://api.reliefweb.int/v1/reports"
    "?appname=nexusglobe"
    "&profile=full"
    "&preset=latest"
    "&limit=50"
    "&fields[include][]=title"
    "&fields[include][]=date"
    "&fields[include][]=primary_country"
    "&fields[include][]=source"
    "&fields[include][]=body-html"
    "&fields[include][]=url"
    "&filter[field]=primary_country.status&filter[value]=crisis"
)

LIVEUAMAP_RSS = "https://liveuamap.com/rss"

# Fallback RSS feeds when Liveuamap is unavailable
FALLBACK_RSS_FEEDS = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
]

# Category → severity base
_RELIEFWEB_CRISIS_SEVERITY = 3

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_reliefweb_entry(item: dict) -> dict | None:
    """Convert one ReliefWeb API item to a normalised event dict."""
    try:
        fields = item.get("fields", {})
        country_info = fields.get("primary_country") or {}
        country = (
            country_info.get("name", "") if isinstance(country_info, dict) else ""
        )

        # ReliefWeb doesn't always provide lat/lng — skip entries without coords
        lat = fields.get("Country", {}).get("iso3", None)  # placeholder check
        # Use country centroid fallback via a small lookup (skip unknown)
        centroid = _COUNTRY_CENTROIDS.get(country)
        if centroid is None:
            return None

        raw_date: str = (fields.get("date") or {}).get("created", "")
        try:
            occurred = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            occurred = datetime.now(timezone.utc)

        title: str = fields.get("title", "Military/Humanitarian report")[:200]
        source_url: str = (fields.get("url") or "")

        source_list = fields.get("source") or []
        reporter = (
            source_list[0].get("name", "ReliefWeb")
            if isinstance(source_list, list) and source_list
            else "ReliefWeb"
        )

        return {
            "event_type": "conflict",
            "category": "military_osint",
            "title": title,
            "description": f"[ReliefWeb] {title}",
            "latitude": centroid[0],
            "longitude": centroid[1],
            "severity": _RELIEFWEB_CRISIS_SEVERITY,
            "source": "military_osint",
            "source_id": f"rw-{item.get('id', '')}",
            "source_url": source_url,
            "occurred_at": occurred.isoformat(),
            "expires_at": (occurred + timedelta(days=7)).isoformat(),
            "metadata": {
                "osint_source": "reliefweb",
                "reported_by": reporter,
                "country": country,
                "verification_status": "unverified",
                "raw_id": item.get("id"),
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("ReliefWeb parse error: %s", exc)
        return None


def _parse_rss_entry(item: ElementTree.Element, feed_source: str) -> dict | None:
    """Convert one RSS <item> to a normalised event dict."""
    ns = {"media": "http://search.yahoo.com/mrss/"}
    try:
        title = (item.findtext("title") or "").strip()[:200]
        description = (item.findtext("description") or "").strip()[:500]
        link = (item.findtext("link") or "").strip()
        pub_date_str = item.findtext("pubDate") or ""
        lat_str = item.findtext("{http://www.w3.org/2003/01/geo/wgs84_pos#}lat") or ""
        lng_str = item.findtext("{http://www.w3.org/2003/01/geo/wgs84_pos#}long") or ""

        # Skip entries without geo data for now
        if not lat_str or not lng_str:
            return None

        try:
            lat = float(lat_str)
            lng = float(lng_str)
        except ValueError:
            return None

        try:
            occurred = parsedate_to_datetime(pub_date_str).astimezone(timezone.utc)
        except Exception:  # noqa: BLE001
            occurred = datetime.now(timezone.utc)

        # Derive source_id from link hash
        import hashlib
        source_id = f"osint-{hashlib.sha1(link.encode()).hexdigest()[:12]}"

        return {
            "event_type": "conflict",
            "category": "military_osint",
            "title": title,
            "description": description,
            "latitude": lat,
            "longitude": lng,
            "severity": 3,
            "source": "military_osint",
            "source_id": source_id,
            "source_url": link,
            "occurred_at": occurred.isoformat(),
            "expires_at": (occurred + timedelta(days=7)).isoformat(),
            "metadata": {
                "osint_source": feed_source,
                "reported_by": feed_source,
                "verification_status": "unverified",
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("RSS parse error (%s): %s", feed_source, exc)
        return None


# ---------------------------------------------------------------------------
# Minimal country-centroid lookup (latitude, longitude) for known crisis zones
# ---------------------------------------------------------------------------

_COUNTRY_CENTROIDS: dict[str, tuple[float, float]] = {
    "Afghanistan":               (33.9391, 67.7100),
    "Central African Republic":  (6.6111, 20.9394),
    "Democratic Republic of the Congo": (-4.0383, 21.7587),
    "Ethiopia":                  (9.1450, 40.4897),
    "Haiti":                     (18.9712, -72.2852),
    "Iraq":                      (33.2232, 43.6793),
    "Libya":                     (26.3351, 17.2283),
    "Mali":                      (17.5707, -3.9962),
    "Mozambique":                 (-18.6657, 35.5296),
    "Myanmar":                   (21.9162, 95.9560),
    "Nigeria":                   (9.0820, 8.6753),
    "Palestine":                 (31.9522, 35.2332),
    "Somalia":                   (5.1521, 46.1996),
    "South Sudan":               (6.8770, 31.3070),
    "Sudan":                     (12.8628, 30.2176),
    "Syria":                     (34.8021, 38.9968),
    "Ukraine":                   (48.3794, 31.1656),
    "Yemen":                     (15.5527, 48.5164),
    "Burkina Faso":              (12.3641, -1.5367),
    "Cameroon":                  (7.3697, 12.3547),
    "Colombia":                  (4.5709, -74.2973),
    "Honduras":                  (15.1999, -86.2419),
    "Iran":                      (32.4279, 53.6880),
    "Israel":                    (31.0461, 34.8516),
    "Lebanon":                   (33.8547, 35.8623),
    "Niger":                     (17.6078, 8.0817),
    "Pakistan":                  (30.3753, 69.3451),
    "Venezuela":                 (6.4238, -66.5897),
    "Mexico":                    (23.6345, -102.5528),
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MilitaryOSINTService(BaseIngestionService):
    """Aggregate military OSINT from public feeds (no API key required)."""

    source_name = "military_osint"
    poll_interval_seconds = 300  # 5 minutes

    async def fetch_raw(self) -> dict[str, Any]:
        """Fetch ReliefWeb API + optional RSS feeds concurrently."""
        raw: dict[str, Any] = {"reliefweb": [], "rss": {}}
        async with httpx.AsyncClient(timeout=20) as client:
            # ── ReliefWeb ──────────────────────────────────────────────────
            try:
                resp = await client.get(RELIEFWEB_URL, follow_redirects=True)
                resp.raise_for_status()
                data = resp.json()
                raw["reliefweb"] = data.get("data") or []
            except Exception as exc:  # noqa: BLE001
                logger.warning("ReliefWeb fetch failed: %s", exc)

            # ── Liveuamap RSS ──────────────────────────────────────────────
            for feed_url, feed_name in [
                (LIVEUAMAP_RSS, "liveuamap"),
                *[(u, "rss_fallback") for u in FALLBACK_RSS_FEEDS],
            ]:
                try:
                    resp = await client.get(feed_url, follow_redirects=True)
                    resp.raise_for_status()
                    raw["rss"][feed_name] = resp.text
                except Exception as exc:  # noqa: BLE001
                    logger.debug("RSS feed %s unavailable: %s", feed_name, exc)

        return raw

    async def normalize(self, raw: dict[str, Any]) -> list[dict]:
        events: list[dict] = []

        # ── ReliefWeb ──────────────────────────────────────────────────────
        for item in raw.get("reliefweb") or []:
            ev = _parse_reliefweb_entry(item)
            if ev is not None:
                events.append(ev)

        # ── RSS feeds ─────────────────────────────────────────────────────
        for feed_name, xml_text in (raw.get("rss") or {}).items():
            try:
                root = ElementTree.fromstring(xml_text)
                items = root.findall(".//item")
                for item in items:
                    ev = _parse_rss_entry(item, feed_name)
                    if ev is not None:
                        events.append(ev)
            except ElementTree.ParseError as exc:
                logger.warning("RSS XML parse error (%s): %s", feed_name, exc)

        return events

    # ------------------------------------------------------------------
    # Override ingest() to add per-source logging
    # ------------------------------------------------------------------

    async def ingest(self) -> int:
        raw = await self.fetch_raw()
        events = await self.normalize(raw)
        if not events:
            logger.info("Military OSINT: no events returned")
            return 0

        counter: Counter[str] = Counter(
            ev.get("metadata", {}).get("osint_source", "unknown") for ev in events
        )

        from app.services.dedup import upsert_events  # avoid circular import
        count = await upsert_events(events)

        sources_str = ", ".join(f"{n} {k}" for k, n in counter.most_common())
        logger.info(
            "Military OSINT: ingested %d reports (%s)", len(events), sources_str
        )
        return count
