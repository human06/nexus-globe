"""Conflict Data Ingestion via GDELT Events v2 — free, no API key required.

Downloads the GDELT v2 export CSV every 30 minutes (15-min batches),
filters QuadClass 3 (Verbal Conflict) and 4 (Material Conflict) events,
and maps them to the GlobeEvent schema.

GDELT Events API: https://www.gdeltproject.org/data.html
lastupdate.txt:   http://data.gdeltproject.org/gdeltv2/lastupdate.txt

CAMEO conflict root codes used:
  14 = PROTEST             → protest
  15 = EXHIBIT FORCE POSTURE → military_posture
  17 = COERCE              → coercion
  18 = ASSAULT             → assault
  19 = FIGHT               → battle
  20 = ENGAGE IN MASS VIOLENCE → mass_violence

GoldsteinScale → severity:
  < -7   → 5  (extreme violence)
  -7..-5 → 4  (serious conflict)
  -5..-3 → 3  (moderate conflict)
  -3..0  → 2  (minor conflict)
  >= 0   → 1  (verbal only)
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any
from collections import Counter

import httpx

from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)

LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"

# CAMEO EventRootCode → internal category
_ROOT_CODE_MAP: dict[str, str] = {
    "14": "protest",
    "15": "military_posture",
    "17": "coercion",
    "18": "assault",
    "19": "battle",
    "20": "mass_violence",
}

# GDELT v2 export CSV column indices (0-based, tab-delimited)
_COL = {
    "event_id":      0,
    "date":          1,   # YYYYMMDD
    "event_code":    26,
    "base_code":     27,
    "root_code":     28,
    "quad_class":    29,  # 3=VerbalConflict 4=MatConflict
    "goldstein":     30,
    "num_mentions":  31,
    "avg_tone":      34,
    "geo_type":      50,  # 3=US city 4=world city 5=world state
    "geo_fullname":  51,
    "geo_country":   52,
    "geo_lat":       55,
    "geo_long":      56,
    "date_added":    58,
    "source_url":    59,
}


def _goldstein_to_severity(gs: float) -> int:
    if gs < -7:
        return 5
    if gs < -5:
        return 4
    if gs < -3:
        return 3
    if gs < 0:
        return 2
    return 1


def _cameo_category(root_code: str) -> str:
    return _ROOT_CODE_MAP.get(root_code, "conflict")


class ACLEDIngestionService(BaseIngestionService):
    """Ingests global conflict events from GDELT Events v2 (every 30 min, free)."""

    source_name = "gdelt_conflict"
    poll_interval_seconds = 1800  # 30 minutes

    # ------------------------------------------------------------------ #
    # fetch_raw                                                            #
    # ------------------------------------------------------------------ #

    async def fetch_raw(self) -> Any:
        """Fetch latest GDELT events CSV, return list of row lists."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Step 1: get the latest file URL from lastupdate.txt
                resp = await client.get(LASTUPDATE_URL)
                resp.raise_for_status()
                lines = resp.text.strip().splitlines()

            # Format: "size hash url" — URL is field [2]
            export_url = None
            for line in lines:
                if "export" in line:
                    parts = line.split()
                    export_url = parts[2] if len(parts) >= 3 else parts[0]
                    break

            if not export_url:
                logger.error("[gdelt_conflict] Could not parse lastupdate.txt")
                return None

            logger.info("[gdelt_conflict] Downloading %s", export_url)

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(export_url)
                resp.raise_for_status()
                zip_bytes = resp.content

        except Exception as exc:
            logger.error("[gdelt_conflict] Fetch failed: %s: %s", type(exc).__name__, exc)
            return None

        # Step 2: unzip and read CSV rows
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                csv_filename = zf.namelist()[0]
                with zf.open(csv_filename) as f:
                    raw_text = f.read().decode("utf-8", errors="replace")
        except Exception as exc:
            logger.error("[gdelt_conflict] Unzip failed: %s", exc)
            return None

        rows = [line.split("\t") for line in raw_text.strip().splitlines() if line]
        logger.info("[gdelt_conflict] Fetched %d raw event rows", len(rows))
        return rows

    # ------------------------------------------------------------------ #
    # normalize                                                            #
    # ------------------------------------------------------------------ #

    async def normalize(self, raw: Any) -> list[dict]:
        if not raw:
            return []

        events: list[dict] = []
        category_counts: Counter[str] = Counter()
        now = datetime.now(timezone.utc)

        for row in raw:
            # Minimum column count check
            if len(row) < 60:
                continue

            # Filter: only QuadClass 3 (Verbal Conflict) or 4 (Material Conflict)
            try:
                quad = int(row[_COL["quad_class"]])
            except (ValueError, IndexError):
                continue
            if quad not in (3, 4):
                continue

            # Coordinates — require world city / world state level precision
            try:
                lat = float(row[_COL["geo_lat"]])
                lng = float(row[_COL["geo_long"]])
            except (ValueError, IndexError):
                continue
            if lat == 0.0 and lng == 0.0:
                continue

            # GoldsteinScale
            try:
                goldstein = float(row[_COL["goldstein"]])
            except (ValueError, IndexError):
                goldstein = -1.0

            severity = _goldstein_to_severity(goldstein)

            # Root code → category
            root_code = row[_COL["root_code"]].strip()
            category  = _cameo_category(root_code)

            # Date
            date_str = row[_COL["date"]].strip()
            try:
                event_dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                event_dt = now

            expires_at = event_dt + timedelta(days=14)

            # Location / title
            geo_name   = row[_COL["geo_fullname"]].strip() or "Unknown location"
            geo_cty    = row[_COL["geo_country"]].strip()
            source_url = row[_COL["source_url"]].strip() if len(row) > _COL["source_url"] else ""
            event_code = row[_COL["event_code"]].strip()
            event_id   = row[_COL["event_id"]].strip()

            title = f"{category.replace('_', ' ').title()} event in {geo_name}"

            try:
                num_mentions = int(row[_COL["num_mentions"]])
            except (ValueError, IndexError):
                num_mentions = 1

            event: dict = {
                "event_type":  "conflict",
                "category":    category,
                "title":       title,
                "description": f"GDELT conflict event ({event_code}) in {geo_name}. Goldstein scale: {goldstein:+.1f}. Mentions: {num_mentions}.",
                "latitude":    lat,
                "longitude":   lng,
                "altitude_m":  0.0,
                "severity":    severity,
                "source":      "gdelt_conflict",
                "source_id":   event_id,
                "source_url":  source_url,
                "expires_at":  expires_at,
                "metadata": {
                    "event_code":    event_code,
                    "root_code":     root_code,
                    "quad_class":    quad,
                    "goldstein":     goldstein,
                    "num_mentions":  num_mentions,
                    "geo_fullname":  geo_name,
                    "geo_country":   geo_cty,
                    "event_date":    date_str,
                },
            }
            events.append(event)
            category_counts[category] += 1

        total = len(events)
        summary = ", ".join(f"{n} {cat}" for cat, n in category_counts.most_common(6))
        logger.info("[gdelt_conflict] normalised %d conflict events (%s)", total, summary or "none")
        return events
