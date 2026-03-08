"""GDELT Ingestion — Story 2.3 (Tier 3 — Deep).

Consumes GDELT v2 Events data via the 15-minute bulk CSV snapshots hosted at
data.gdeltproject.org — free, unauthenticated, no rate limit.

Flow (every 60 seconds):
  1. GET lastupdate.txt  →  extract URL of the latest export.CSV.zip
  2. Download + unzip the ~80 KB CSV (tab-separated, ~1–3 k rows)
  3. Parse each row, extract ActionGeo lat/lng, GoldsteinScale, QuadClass, etc.
  4. Deduplicate by SOURCEURL (many GDELT rows share the same article)
  5. Cross-source check: mark events that already exist in Tier 1/2 as
     enrichment candidates via ``metadata.gdelt_enriched = True``
     (full merge is Story 2.7 — here we just upsert with source="gdelt")

GDELT v2 Events CSV columns (61, tab-separated, 0-indexed) — key subset:
  1  SQLDATE     YYYYMMDD
  6  Actor1Name
  16 Actor2Name
  26 EventCode   CAMEO code
  28 EventRootCode
  29 QuadClass   1=verb-coop 2=mat-coop 3=verb-conflict 4=mat-conflict
  30 GoldsteinScale  −10..+10
  31 NumMentions
  34 AvgTone
  52 ActionGeo_FullName
  56 ActionGeo_Lat
  57 ActionGeo_Long
  60 SOURCEURL

Severity ← GoldsteinScale (−10..+10):
  ≤ −7  →  5  |  ≤ −3  →  4  |  ≤ 0  →  3  |  ≤ 5  →  2  |  > 5  →  1
"""
from __future__ import annotations

import csv
import io
import logging
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GDELT data source
# ---------------------------------------------------------------------------
_LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"

# ---------------------------------------------------------------------------
# GDELT v2 Events CSV column indices (0-based, 61 total columns)
# ---------------------------------------------------------------------------
_C_DATE    = 1
_C_ACT1    = 6
_C_ACT2    = 16
_C_EVCODE  = 26
_C_EVRCODE = 28
_C_QUAD    = 29
_C_GOLD    = 30
_C_TONE    = 34
_C_GEONAME = 52
_C_GEOLAT  = 56
_C_GEOLONG = 57
_C_URL     = 60
_MIN_COLS  = 61

# ---------------------------------------------------------------------------
# CAMEO EventRootCode (2-char) → internal category
# ---------------------------------------------------------------------------
_CAMEO_CATEGORY: dict[str, str] = {
    "01": "news",     "02": "news",     "03": "news",  "04": "news",
    "05": "news",     "06": "news",     "07": "news",  "08": "news",
    "09": "news",     "10": "politics", "11": "politics",
    "12": "politics", "13": "politics", "14": "politics",
    "15": "conflict", "16": "conflict", "17": "conflict",
    "18": "conflict", "19": "conflict", "20": "conflict",
}


def _goldstein_to_severity(gs: str) -> int:
    try:
        g = float(gs)
    except (ValueError, TypeError):
        return 3
    if g <= -7:
        return 5
    if g <= -3:
        return 4
    if g <= 0:
        return 3
    if g <= 5:
        return 2
    return 1


def _cameo_to_category(root_code: str, quad_class: str) -> str:
    if quad_class == "4":
        return "conflict"
    return _CAMEO_CATEGORY.get(root_code[:2], "news")


def _parse_sqldate(s: str) -> datetime:
    try:
        return datetime.strptime(s.strip(), "%Y%m%d").replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


def _source_id(url: str) -> str:
    return sha256(url.encode()).hexdigest()[:16]


# Common short/stopwords that alone don't form a meaningful headline
_SLUG_STOPWORDS = frozenset({
    "the", "a", "an", "in", "on", "at", "to", "of", "and", "or", "for",
    "by", "as", "is", "it", "up", "be", "vs", "de", "la", "le", "les",
})


def _slug_title(url: str) -> str | None:
    """
    Try to extract a human-readable headline from the news article URL slug.

    e.g. ``https://reuters.com/world/ukraine-russia-talks-2026-03-07/``
    → ``"Ukraine Russia Talks"``

    Returns *None* when the slug doesn't yield ≥ 3 content words.
    """
    try:
        path  = urlparse(url).path.rstrip("/")
        slug  = path.split("/")[-1]

        # Strip trailing date patterns: 2026-03-07, 20260307
        slug = re.sub(r"-?\d{4}-\d{2}-\d{2}$", "", slug)
        slug = re.sub(r"-?\d{8}$", "",  slug)
        # Strip wire-service ID suffixes like idUSKBN2... or -SB12345
        slug = re.sub(r"-?id[A-Z]{2}[A-Z0-9]{5,}", "", slug, flags=re.IGNORECASE)
        slug = re.sub(r"-?[A-Z]{2}[0-9]{5,}",      "", slug, flags=re.IGNORECASE)

        # Split on hyphens / underscores; filter noise tokens
        words = [
            w for w in re.split(r"[-_]+", slug)
            if len(w) >= 2
            and not w.isdigit()
            and not re.fullmatch(r"[a-f0-9]{6,}", w, re.IGNORECASE)
            and w.lower() not in _SLUG_STOPWORDS
        ]

        if len(words) >= 3:
            return " ".join(w.capitalize() for w in words)[:120]
    except Exception:  # noqa: BLE001
        pass
    return None


def _tidy(s: str) -> str:
    """Title-case an ALL-CAPS GDELT string and deduplicate comma-separated parts."""
    # Remove duplicate suffixes like "Egypt, Egypt"
    parts = [p.strip() for p in s.split(",")]
    seen: list[str] = []
    for p in parts:
        if p.lower() not in (x.lower() for x in seen):
            seen.append(p)
    return ", ".join(p.title() for p in seen)


def _extract_export_url(text: str) -> str | None:
    """Parse lastupdate.txt and return the export.CSV.zip URL."""
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 3 and "export.CSV.zip" in parts[2]:
            return parts[2]
    return None


class GDELTIngestionService(BaseIngestionService):
    """Tier-3 deep news source — GDELT v2 Events CSV, free, no auth."""

    source_name = "gdelt"
    poll_interval_seconds = 60

    def __init__(self) -> None:
        super().__init__()
        self._last_export_url: str | None = None  # avoid re-downloading same 15-min chunk

    # ---------------------------------------------------------------------------
    # BaseIngestionService interface
    # ---------------------------------------------------------------------------

    async def fetch_raw(self) -> dict[str, Any] | None:
        """
        1. Fetch lastupdate.txt to find the current export.CSV.zip URL.
        2. Skip if we already processed this 15-min chunk.
        3. Download + unzip the CSV (~80 KB compressed).

        Returns ``{"rows": [[col, ...], ...], "export_url": str}`` or ``None``.
        """
        t0 = time.monotonic()

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            # Step 1 — resolve current export file
            try:
                resp = await client.get(_LASTUPDATE_URL)
                resp.raise_for_status()
                export_url = _extract_export_url(resp.text)
            except Exception as exc:
                logger.warning("[gdelt] lastupdate.txt fetch failed: %s", exc)
                return None

            if not export_url:
                logger.warning("[gdelt] Could not parse export URL from lastupdate.txt")
                return None

            if export_url == self._last_export_url:
                logger.debug("[gdelt] Same export file as last cycle — skipping")
                return None

            # Step 2 — download zip
            try:
                resp = await client.get(export_url)
                resp.raise_for_status()
                zip_bytes = resp.content
            except Exception as exc:
                logger.warning("[gdelt] export CSV download failed: %s", exc)
                return None

        # Step 3 — unzip + parse CSV (in-memory, fast)
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                csv_name = next((n for n in zf.namelist() if n.endswith(".CSV")), None)
                if not csv_name:
                    logger.warning("[gdelt] No .CSV file in zip")
                    return None
                csv_bytes = zf.read(csv_name)
        except Exception as exc:
            logger.warning("[gdelt] zip extract failed: %s", exc)
            return None

        text   = csv_bytes.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text), delimiter="\t")
        rows   = [row for row in reader if len(row) >= _MIN_COLS]

        self._last_export_url = export_url
        logger.info(
            "[gdelt] Downloaded %s — %d rows in %.1fs",
            export_url.split("/")[-1], len(rows), time.monotonic() - t0,
        )
        return {"rows": rows, "export_url": export_url}

    async def normalize(self, raw: dict[str, Any] | None) -> list[dict]:
        """
        Convert GDELT event rows → GlobeEvent dicts.

        One GDELT row = one actor-interaction event (not one article).
        Many rows share the same SOURCEURL — we deduplicate by URL, keeping
        the row with the highest |GoldsteinScale| (most significant event).
        """
        if not raw:
            return []

        rows: list[list[str]] = raw.get("rows", [])

        # Deduplicate by SOURCEURL — keep highest |Goldstein| row per URL
        best: dict[str, list[str]] = {}
        for row in rows:
            url = row[_C_URL].strip()
            if not url:
                continue
            try:
                gs = abs(float(row[_C_GOLD]))
            except (ValueError, IndexError):
                gs = 0.0
            existing_gs = 0.0
            if url in best:
                try:
                    existing_gs = abs(float(best[url][_C_GOLD]))
                except (ValueError, IndexError):
                    pass
            if gs >= existing_gs:
                best[url] = row

        events: list[dict] = []
        skipped = 0

        for url, row in best.items():
            # Coordinates
            try:
                lat = float(row[_C_GEOLAT])  if row[_C_GEOLAT].strip()  else None
                lng = float(row[_C_GEOLONG]) if row[_C_GEOLONG].strip() else None
            except (ValueError, IndexError):
                lat = lng = None

            if lat is not None and not (-90 <= lat <= 90):
                lat = lng = None
            if lng is not None and not (-180 <= lng <= 180):
                lat = lng = None

            root_code = row[_C_EVRCODE].strip()
            quad      = row[_C_QUAD].strip()
            goldstein = row[_C_GOLD].strip()
            tone      = row[_C_TONE].strip()
            geo_name  = row[_C_GEONAME].strip()
            act1      = row[_C_ACT1].strip()
            act2      = row[_C_ACT2].strip()
            sqldate   = row[_C_DATE].strip()

            # Build a readable title — prefer URL slug headline; fall back to actors/geo
            actors    = " / ".join(filter(None, [act1, act2]))
            slug_title = _slug_title(url)

            if slug_title:
                title = slug_title
            elif actors and geo_name:
                title = f"{_tidy(actors)} — {_tidy(geo_name)}"
            elif geo_name:
                title = f"Event in {_tidy(geo_name)}"
            elif actors:
                title = f"Event: {_tidy(actors)}"
            else:
                skipped += 1
                continue

            category  = _cameo_to_category(root_code, quad)
            severity  = _goldstein_to_severity(goldstein)
            published = _parse_sqldate(sqldate)
            # Expire based on ingestion time so GDELT events (whose published
            # date is YYYYMMDD with no time component, defaulting to midnight)
            # don't expire immediately when ingested late in the day.
            now_utc   = datetime.now(timezone.utc)
            expires   = max(published + timedelta(hours=24), now_utc + timedelta(hours=24))

            events.append({
                "event_type":  "news",
                "category":    category,
                "title":       title[:200],
                "description": f"GDELT {row[_C_EVCODE].strip()} — {geo_name}",
                "latitude":    lat,
                "longitude":   lng,
                "severity":    severity,
                "source":      "gdelt",
                "source_id":   _source_id(url),
                "source_url":  url,
                "expires_at":  expires,
                "metadata": {
                    "gdelt_enriched":  True,
                    "gdelt_themes":    [],
                    "goldstein_scale": float(goldstein) if goldstein else None,
                    "avg_tone":        float(tone)      if tone      else None,
                    "cameo_code":      row[_C_EVCODE].strip(),
                    "cameo_root_code": root_code,
                    "quad_class":      quad,
                    "actors":          [a for a in [act1, act2] if a],
                    "location_name":   geo_name,
                    "source_domain":   url.split("/")[2] if url.count("/") >= 2 else "",
                    "language":        "en",
                    "needs_geocoding": lat is None,
                    "published_date":  published.isoformat(),
                },
            })

        # Log summary
        cat_counts: dict[str, int] = {}
        for ev in events:
            cat_counts[ev["category"]] = cat_counts.get(ev["category"], 0) + 1
        breakdown = ", ".join(
            f"{c} {k}" for k, c in sorted(cat_counts.items(), key=lambda x: -x[1])
        )
        geocoded  = sum(1 for e in events if e["latitude"] is not None)
        needs_geo = len(events) - geocoded

        logger.info(
            "GDELT: ingested %d events (%d geocoded, %d needs-geo) — %s — %d skipped",
            len(events), geocoded, needs_geo, breakdown or "none", skipped,
        )
        return events
