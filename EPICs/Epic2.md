# NEXUS GLOBE — Epic 2: Intelligence Awakens

### Three-Tier News Pipeline + Disasters + Ships + AI Enrichment (OpenRouter)

---

## Epic Summary

**Goal:** Transform the globe from a flight tracker into a true intelligence dashboard by adding a **three-tier breaking news pipeline** (wire services → Event Registry → GDELT), natural disaster tracking, ship tracking, AI event enrichment via OpenRouter, and a scrolling news ticker. When this epic is done, breaking news appears on the globe within minutes of happening, earthquakes pulse red rings, ships drift along glowing green lanes, and an AI model of your choice summarizes everything.

**Prerequisite:** Epic 1 fully complete (globe rendering, WebSocket pipeline, flight layer working).

**Definition of Done:** User opens the app and sees 4 active layers simultaneously — flights (yellow), news events (cyan), disasters (red), and ships (green) — with breaking headlines appearing within 5 minutes, AI-generated summaries on click, and a live ticker scrolling at the bottom.

---

## Three-Tier Breaking News Architecture

Speed matters. Instead of relying on one source, we use three tiers that complement each other:

```mermaid
flowchart LR
    subgraph "Tier 1 — FAST (2-5 min delay)"
        RSS[RSS Wire Feeds<br/>Reuters, AP, BBC,<br/>Al Jazeera]
    end

    subgraph "Tier 2 — SMART (5-15 min delay)"
        ER[Event Registry<br/>Clustered events<br/>+ geocoding]
    end

    subgraph "Tier 3 — DEEP (15-60 min delay)"
        GD[GDELT<br/>65 languages<br/>global coverage]
    end

    RSS -->|30s poll| NP[News Normalizer]
    ER -->|120s poll| NP
    GD -->|60s poll| NP

    NP --> DEDUP[Dedup Engine<br/>merge same story<br/>from 3 sources]
    DEDUP --> AI[OpenRouter AI<br/>geocode + enrich<br/>+ severity]
    AI --> DB[(PostgreSQL)]
    AI --> WS[WebSocket → Globe]

    style RSS fill:#ff2244,color:#fff
    style ER fill:#ff6600,color:#fff
    style GD fill:#00f0ff,color:#000
    style AI fill:#ff00aa,color:#fff
```

| Tier | Source | Delay | Strength | Weakness | Poll |
|------|--------|-------|----------|----------|------|
| **1. Fast** | RSS (Reuters, AP, BBC, Al Jazeera) | 2-5 min | Speed — first to report | No geocoding, needs AI to add lat/lng | 30s |
| **2. Smart** | Event Registry | 5-15 min | Pre-clustered, geocoded, deduplicated | Free tier: 200 req/day | 120s |
| **3. Deep** | GDELT | 15-60 min | 65 languages, massive global coverage | Slow, noisy, needs heavy filtering | 60s |

**How they work together:** Tier 1 (RSS) catches breaking news fast but has no coordinates — the AI enricher geocodes it. Tier 2 (Event Registry) arrives minutes later with better structure and confirms/merges with Tier 1. Tier 3 (GDELT) fills in global coverage hours later with articles from local media in 65 languages that Reuters/AP never picked up.

---

## Architecture Context — What This Epic Adds

```mermaid
flowchart TB
    subgraph Epic 1 — Already Built
        OS[OpenSky ✈️] -->|10s| ING
        ING[Ingestion Engine] --> DB[(PostgreSQL)]
        ING --> RD[(Redis)]
        RD --> WS[WebSocket] --> FE[Globe Frontend]
    end

    subgraph Epic 2 — New
        RSS[RSS Wires 📰] -->|30s| ING
        ER[Event Registry 📰] -->|120s| ING
        GD[GDELT 📰] -->|60s| ING
        US[USGS 🌋] -->|60s| ING
        EO[NASA EONET 🔥] -->|300s| ING
        AIS[AISHub 🚢] -->|60s| ING

        ING -->|news events| AI[OpenRouter AI<br/>geocode + enrich]
        AI -->|enriched| DB

        FE --> NL[News Layer<br/>Cyan pulses]
        FE --> DL[Disaster Layer<br/>Red rings]
        FE --> SL[Ship Layer<br/>Green diamonds]
        FE --> TK[News Ticker<br/>Scrolling bar]
    end

    style RSS fill:#ff2244,color:#fff
    style ER fill:#ff6600,color:#fff
    style GD fill:#00f0ff,color:#000
    style US fill:#ff2244,color:#fff
    style EO fill:#ff2244,color:#fff
    style AIS fill:#00ff88,color:#000
    style AI fill:#ff00aa,color:#fff
```

---

## AI Provider Architecture — OpenRouter

All AI features route through **OpenRouter** — a unified gateway to 200+ LLM models. Zero vendor lock-in.

```env
# === AI CONFIGURATION (OpenRouter) ===
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
AI_MODEL=google/gemini-2.5-flash-preview
AI_MODEL_FALLBACK=deepseek/deepseek-chat-v3-0324
AI_MAX_TOKENS=500
AI_TEMPERATURE=0.3
AI_MAX_REQUESTS_PER_MINUTE=30
```

| Model | Speed | Quality | Cost | Best For |
|-------|-------|---------|------|----------|
| `google/gemini-2.5-flash-preview` | ⚡ Fast | ★★★★ | $$ | Default — good balance |
| `deepseek/deepseek-chat-v3-0324` | ⚡ Fast | ★★★★ | $ | Budget option |
| `meta-llama/llama-4-maverick` | ⚡ Fast | ★★★★ | $ | Open-source alternative |
| `anthropic/claude-sonnet-4` | Medium | ★★★★★ | $$$$ | Premium when needed |
| `qwen/qwen3-235b-a22b` | Medium | ★★★★ | $$ | Multilingual events |
| `openai/gpt-4.1-mini` | ⚡ Fast | ★★★★ | $$ | Reliable structured output |

---

## Stories

This epic contains **14 stories** — 8 backend, 6 frontend — building a multi-layered intelligence view.

---

### STORY 2.1 — RSS Wire Service Ingestion (Tier 1 — Fast)
**Track:** Backend
**Points:** 5
**Priority:** P0 — Core Feature

#### Description
Implement real-time news ingestion from major wire service RSS feeds. This is our **fastest news source** — Reuters, AP, BBC, and Al Jazeera publish RSS within minutes of events. RSS items don't include geocoding, so the AI enricher (Story 2.6) will add lat/lng coordinates.

#### Acceptance Criteria
- [ ] `RSSWireService` extends `BaseIngestionService`
- [ ] Parses RSS/Atom feeds from these sources (configurable list):
  ```
  Reuters World:     https://www.reutersagency.com/feed/?best-topics=world
  AP Top News:       https://rsshub.app/apnews/topics/apf-topnews
  BBC World:         https://feeds.bbci.co.uk/news/world/rss.xml
  Al Jazeera:        https://www.aljazeera.com/xml/rss/all.xml
  France24:          https://www.france24.com/en/rss
  DW (Deutsche Welle): https://rss.dw.com/rdf/rss-en-world
  ```
- [ ] Parses each RSS item into a GlobeEvent:
  - `event_type`: "news"
  - `category`: "breaking" (until AI enricher recategorizes)
  - `title`: RSS title (truncated to 200 chars)
  - `description`: RSS description/summary (first 500 chars)
  - `latitude/longitude`: **null initially** — flagged for AI geocoding
  - `severity`: 3 (default, until AI enricher rescores)
  - `source`: feed name (e.g., "reuters", "bbc", "ap")
  - `source_id`: RSS GUID or link URL hash
  - `sourceUrl`: article link
  - `metadata`: `{ feed_source, published_date, categories[], author, needs_geocoding: true }`
  - `expires_at`: 24 hours from publish time
- [ ] Detects duplicate articles across feeds (same story on Reuters + AP + BBC)
  - Dedup by: title similarity > 80% (fuzzy match) within 2-hour window
  - Keep the earliest version, link others as `metadata.also_reported_by[]`
- [ ] Poll interval: **30 seconds** (RSS feeds are lightweight)
- [ ] Uses `httpx` with proper User-Agent header and ETag/If-Modified-Since for efficiency
- [ ] Handles feed downtime gracefully (skip, log, retry next cycle)
- [ ] Events with `needs_geocoding: true` are queued for AI enrichment (Story 2.6)
- [ ] Logs: `"RSS Wires: ingested 12 articles (4 Reuters, 3 BBC, 3 AP, 2 AJ) in 0.8s"`

#### Technical Notes
```python
import httpx
import feedparser
from hashlib import sha256

RSS_FEEDS = {
    "reuters": "https://www.reutersagency.com/feed/?best-topics=world",
    "ap": "https://rsshub.app/apnews/topics/apf-topnews",
    "bbc": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "aljazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "france24": "https://www.france24.com/en/rss",
    "dw": "https://rss.dw.com/rdf/rss-en-world",
}

class RSSWireService(BaseIngestionService):
    source_name = "rss_wires"
    poll_interval_seconds = 30
    
    async def fetch_raw(self) -> dict:
        results = {}
        async with httpx.AsyncClient() as client:
            for name, url in RSS_FEEDS.items():
                try:
                    resp = await client.get(url, headers={"User-Agent": "NexusGlobe/1.0"})
                    feed = feedparser.parse(resp.text)
                    results[name] = feed.entries
                except Exception as e:
                    logger.warning(f"RSS feed {name} failed: {e}")
        return results
    
    async def normalize(self, raw: dict) -> list:
        events = []
        for source_name, entries in raw.items():
            for entry in entries:
                event = GlobeEvent(
                    event_type="news",
                    category="breaking",
                    title=entry.get("title", "")[:200],
                    description=entry.get("summary", "")[:500],
                    latitude=None,   # Needs AI geocoding
                    longitude=None,  # Needs AI geocoding
                    severity=3,
                    source=source_name,
                    source_id=sha256(entry.get("link", "").encode()).hexdigest()[:16],
                    source_url=entry.get("link"),
                    metadata={
                        "feed_source": source_name,
                        "published_date": entry.get("published"),
                        "categories": [t.get("term", "") for t in entry.get("tags", [])],
                        "needs_geocoding": True,
                    },
                )
                events.append(event)
        return events
```

#### Dependencies
- `feedparser` — add to `requirements.txt`

#### Files to Create/Modify
- `backend/app/services/ingestion/rss_wires.py` (new)
- `backend/requirements.txt` (add `feedparser==6.0.11`)
- `backend/app/scheduler.py` (register RSS service)

---

### STORY 2.2 — Event Registry Ingestion (Tier 2 — Smart)
**Track:** Backend
**Points:** 5
**Priority:** P0 — Core Feature

#### Description
Implement Event Registry ingestion as the second-tier news source. Event Registry clusters related articles together, provides geocoding, and assigns categories — making it smarter than raw RSS but slightly slower. Free tier allows 200 API calls/day which is enough for our polling pattern.

#### Acceptance Criteria
- [ ] `EventRegistryService` extends `BaseIngestionService`
- [ ] Fetches from Event Registry API:
  - Endpoint: `https://eventregistry.org/api/v1/minuteStreamArticles`
  - Or batch: `https://eventregistry.org/api/v1/article/getArticles`
- [ ] Requires `EVENT_REGISTRY_API_KEY` from environment (skip gracefully if missing)
- [ ] Parses articles/events into GlobeEvent objects:
  - `event_type`: "news"
  - `category`: from Event Registry classification (politics, business, sports, technology, etc.)
  - `title`: article title
  - `description`: article body excerpt (500 chars)
  - `latitude/longitude`: from Event Registry geocoding (article's main location)
  - `severity`: mapped from Event Registry relevance/importance score:
    - Importance ≥ 80 → severity 5
    - 60-80 → severity 4
    - 40-60 → severity 3
    - 20-40 → severity 2
    - < 20 → severity 1
  - `source`: "event_registry"
  - `source_id`: Event Registry article URI
  - `sourceUrl`: original article URL
  - `metadata`: `{ er_event_uri, er_categories[], er_concepts[], article_count_in_cluster, sentiment, source_domain, languages[], location_label }`
  - `expires_at`: 24 hours from publish time
- [ ] Leverages Event Registry's built-in clustering — if multiple articles about same event, only ingest the cluster leader
- [ ] Merges with existing RSS events (cross-source dedup by location + title similarity)
- [ ] Poll interval: **120 seconds** (to respect 200 req/day free tier limit)
- [ ] Handles missing API key: log warning and skip
- [ ] Logs: `"EventRegistry: ingested 23 events (8 politics, 6 conflict, 9 other) in 1.5s"`

#### Technical Notes
```python
# Event Registry API call
ER_ENDPOINT = "https://eventregistry.org/api/v1/article/getArticles"

params = {
    "apiKey": settings.event_registry_api_key,
    "resultType": "articles",
    "articlesSortBy": "date",
    "articlesCount": 50,
    "lang": "eng",
    "dateStart": (datetime.utcnow() - timedelta(hours=1)).strftime("%Y-%m-%d"),
    "keyword": "",  # Empty = all topics
    "dataType": ["news"],
    "includeArticleLocation": True,
    "includeArticleConcepts": True,
    "includeArticleCategories": True,
}

# Response includes pre-geocoded locations:
# {
#   "articles": {
#     "results": [
#       {
#         "uri": "8234567",
#         "title": "...",
#         "body": "...",
#         "source": { "uri": "reuters.com" },
#         "location": { "lat": 48.8566, "long": 2.3522, "label": "Paris, France" },
#         "categories": [{ "uri": "news/Politics" }],
#         "concepts": [{ "label": "Emmanuel Macron", "type": "person" }],
#         "sentiment": -0.3,
#         "relevance": 85
#       }
#     ]
#   }
# }
```

#### Files to Create/Modify
- `backend/app/services/ingestion/event_registry.py` (new)
- `backend/app/config.py` (add `event_registry_api_key`)
- `backend/app/scheduler.py` (register Event Registry service)

---

### STORY 2.3 — GDELT News Ingestion (Tier 3 — Deep)
**Track:** Backend
**Points:** 5
**Priority:** P0 — Core Feature

#### Description
Implement GDELT as the third-tier news source for deep global coverage. While Tier 1 (RSS) and Tier 2 (Event Registry) catch major English-language news fast, GDELT captures articles in 65 languages from local media worldwide — the earthquake in rural Turkey that only Turkish media reported, the protest in Myanmar covered only by local outlets.

#### Acceptance Criteria
- [ ] `GDELTService` extends `BaseIngestionService`
- [ ] Fetches from GDELT GKG API v2:
  - Primary: `https://api.gdeltproject.org/api/v2/doc/doc?query=&mode=ArtList&maxrecords=250&format=json`
  - Geo-filtered: `https://api.gdeltproject.org/api/v2/geo/geo?query=&mode=PointData&format=GeoJSON`
- [ ] Parses articles into GlobeEvent objects:
  - `event_type`: "news"
  - `category`: derived from GDELT theme taxonomy
  - `severity`: mapped from GoldsteinScale (-10 to +10 → 1-5)
  - `source`: "gdelt"
  - `metadata`: `{ themes[], tone, goldstein_scale, actors[], source_domain, language }`
  - `expires_at`: 24 hours
- [ ] **Cross-source intelligence**: before inserting, checks if same event already exists from Tier 1 (RSS) or Tier 2 (Event Registry):
  - If match found: enriches the existing event with GDELT's additional data (themes, actors, Goldstein score) instead of creating a duplicate
  - Adds `metadata.gdelt_enriched: true` and `metadata.gdelt_themes` to existing event
  - If no match: creates new event (this is a story ONLY GDELT caught)
- [ ] Filters out events already covered by Tier 1/2 within 50km + 2hr window
- [ ] Poll interval: **60 seconds**
- [ ] Logs: `"GDELT: ingested 47 events (12 new, 35 enriched existing) in 2.1s"`

#### Technical Notes
```python
THEME_CATEGORIES = {
    "MILITARY": "military",
    "PROTEST": "politics",
    "TERROR": "conflict",
    "ECON_": "economy",
    "HEALTH_": "health",
    "ENV_": "environment",
    "NATURAL_DISASTER": "disaster",
}

# Goldstein scale to severity mapping
def goldstein_to_severity(score: float) -> int:
    if score <= -7: return 5
    if score <= -3: return 4
    if score <= 0:  return 3
    if score <= 5:  return 2
    return 1
```

#### Files to Create/Modify
- `backend/app/services/ingestion/gdelt.py`
- `backend/app/scheduler.py` (register GDELT service)

---

### STORY 2.4 — USGS Earthquake Ingestion Service
**Track:** Backend
**Points:** 3
**Priority:** P0 — Core Feature

#### Description
Implement the USGS earthquake feed ingestion — real-time GeoJSON feed of earthquakes worldwide, updated every minute.

#### Acceptance Criteria
- [ ] `USGSService` extends `BaseIngestionService`
- [ ] Fetches from:
  - All earthquakes, past hour: `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson`
  - Significant earthquakes, past day: `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_day.geojson`
- [ ] Parses into GlobeEvent: `event_type`: "disaster", `category`: "earthquake"
- [ ] `title`: `"M{mag} Earthquake — {place}"`, `severity`: M<3→1, 3-4.5→2, 4.5-5.5→3, 5.5-7→4, ≥7→5
- [ ] `metadata`: `{ magnitude, mag_type, depth_km, felt_reports, tsunami_flag, alert_level, mmi, cdi, status }`
- [ ] `expires_at`: 7 days from event time
- [ ] Deduplicates by USGS event ID, poll interval: 60 seconds
- [ ] Logs: `"USGS: ingested 12 earthquakes (1 significant M6.2) in 0.8s"`

#### Files to Create/Modify
- `backend/app/services/ingestion/usgs.py`
- `backend/app/scheduler.py`

---

### STORY 2.5 — NASA EONET Natural Disaster Ingestion Service
**Track:** Backend
**Points:** 3
**Priority:** P1 — Important

#### Description
Implement NASA EONET for wildfires, volcanic eruptions, severe storms, floods. Complements USGS by covering non-earthquake natural events.

#### Acceptance Criteria
- [ ] `EONETService` extends `BaseIngestionService`
- [ ] Fetches from: `https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=50`
- [ ] Category mapping: "Wildfires"→"wildfire", "Volcanoes"→"volcanic_eruption", "Severe Storms"→"severe_storm", "Floods"→"flood"
- [ ] Severity: Volcanoes/Storms→4, Wildfires/Floods→3, Drought/Ice→2
- [ ] `trail`: for multi-point events (storm tracks), include all geometry points
- [ ] `expires_at`: 7 days from last update, poll interval: 300 seconds
- [ ] Logs: `"EONET: ingested 8 events (3 wildfires, 2 storms, 3 other) in 1.5s"`

#### Files to Create/Modify
- `backend/app/services/ingestion/eonet.py`
- `backend/app/scheduler.py`

---

### STORY 2.6 — AISHub Ship Tracking Ingestion Service
**Track:** Backend
**Points:** 5
**Priority:** P0 — Core Feature

#### Description
Implement ship tracking via AIS data from AISHub.

#### Acceptance Criteria
- [ ] `AISHubService` extends `BaseIngestionService`
- [ ] Fetches from: `https://data.aishub.net/ws.php?username={API_KEY}&format=1&output=json&compress=0`
- [ ] Requires `AISHUB_API_KEY` (skip gracefully if missing)
- [ ] Ship type mapping: 60-69→"passenger", 70-79→"cargo", 80-89→"tanker", 30-39→"fishing", 50-59→"special"
- [ ] `trail`: last 20 positions, `expires_at`: 120 seconds
- [ ] Dedup by MMSI, filter stationary vessels < 0.5 kts
- [ ] Poll interval: 60 seconds, handles missing API key gracefully
- [ ] `metadata`: `{ mmsi, imo, callsign, ship_type, destination, eta, draught, length, width, flag_country }`
- [ ] Logs: `"AISHub: ingested 2,847 vessels (1,204 cargo, 892 tanker, 751 other) in 3.2s"`

#### Files to Create/Modify
- `backend/app/services/ingestion/aishub.py`
- `backend/app/scheduler.py`
- `backend/app/config.py` (ensure aishub_api_key is optional)

---

### STORY 2.7 — Event Deduplication & Clustering Engine
**Track:** Backend
**Points:** 5
**Priority:** P0 — Critical (three news sources need dedup)

#### Description
With three news sources plus disaster feeds, deduplication is critical. The same breaking story will arrive from Reuters RSS (2 min), Event Registry (10 min), and GDELT (30 min). We need intelligent merging — not three duplicate dots on the globe, but one dot that gets progressively enriched as more sources confirm it.

#### Acceptance Criteria
- [ ] **Same-source dedup**: identical `(source, source_id)` → upsert
- [ ] **Cross-source news dedup** (the key challenge):
  - When a new news event arrives, search for existing events within 50km + 2hr window
  - Use title similarity (fuzzy match > 70%) to confirm it's the same story
  - If match found: **merge, don't duplicate**:
    - Keep the earliest event as primary
    - Append new source to `metadata.confirmed_by[]` array
    - Update severity to max of all sources
    - If new source has better description/geocoding, upgrade those fields
    - Set `metadata.multi_source_confirmed: true`
  - If no match: create new event
- [ ] **Cross-source disaster dedup**: USGS quake + GDELT "earthquake" article within 100km → link, not duplicate
- [ ] **Clustering**: > 5 events within 100km within 4 hours → create meta-event cluster
- [ ] **Progressive enrichment tracking**:
  ```json
  {
    "first_seen": "2024-01-15T12:00:00Z",
    "first_source": "reuters",
    "confirmed_by": ["reuters", "bbc", "event_registry", "gdelt"],
    "confirmation_count": 4,
    "multi_source_confirmed": true,
    "gdelt_enriched": true,
    "ai_enriched": true
  }
  ```
- [ ] Stale event cleanup: events past `expires_at` are soft-deleted
- [ ] Title fuzzy matching uses simple Levenshtein ratio (no heavy ML)
- [ ] Logs: `"Dedup: 73 incoming → 41 new, 27 merged into existing, 5 discarded, 2 clusters"`

#### Technical Notes
```python
from difflib import SequenceMatcher

def titles_match(title1: str, title2: str, threshold: float = 0.7) -> bool:
    """Fuzzy title comparison for cross-source dedup."""
    # Normalize: lowercase, strip source prefixes
    t1 = title1.lower().strip()
    t2 = title2.lower().strip()
    return SequenceMatcher(None, t1, t2).ratio() >= threshold

async def find_matching_event(session, event) -> Event | None:
    """Find existing event that matches this one (cross-source dedup)."""
    # Step 1: Spatial + temporal search
    nearby = await find_nearby_events(
        session, event.latitude, event.longitude,
        radius_meters=50000, time_window_hours=2
    )
    # Step 2: Title similarity check
    for existing in nearby:
        if existing.event_type == event.event_type:
            if titles_match(existing.title, event.title):
                return existing
    return None
```

#### Files to Create/Modify
- `backend/app/services/dedup.py` (full implementation)
- `backend/app/services/ingestion/base.py` (integrate dedup into pipeline)

---

### STORY 2.8 — OpenRouter AI Event Analyzer Service
**Track:** Backend
**Points:** 8
**Priority:** P1 — Key Differentiator

#### Description
Implement the AI analysis pipeline via **OpenRouter**. This service does TWO critical jobs:

1. **Geocoding** — Tier 1 RSS articles have no lat/lng. The AI reads the headline and determines the location (e.g., "Explosion in Beirut port" → 33.9, 35.5).
2. **Enrichment** — Add summaries, severity scores, entity extraction, and categorization to all news events.

The model is configurable via env var — default K2.5, swappable to any OpenRouter model.

#### Acceptance Criteria
- [ ] `AIAnalyzer` service with:
  - `geocode_event(event)` — for events with `needs_geocoding: true`
  - `enrich_event(event)` — full analysis
  - `enrich_batch(events)` — batch of up to 5
- [ ] Uses **httpx** to call OpenRouter's OpenAI-compatible API
- [ ] All config from environment:
  ```
  OPENROUTER_API_KEY, OPENROUTER_BASE_URL, AI_MODEL, AI_MODEL_FALLBACK,
  AI_MAX_TOKENS, AI_TEMPERATURE, AI_MAX_REQUESTS_PER_MINUTE
  ```
- [ ] **Geocoding prompt** (for RSS events without lat/lng):
  ```
  Extract the primary geographic location from this news headline.
  Title: {title}
  Description: {description}
  
  Return JSON: { "latitude": float, "longitude": float, "location_name": string, "confidence": 0-1 }
  If no location can be determined, return { "latitude": null, "longitude": null, "confidence": 0 }
  ```
- [ ] **Enrichment prompt** (for all news events):
  ```
  Analyze this news event and return structured JSON:
  Title: {title} | Source: {source} | Location: {lat}, {lng}
  
  Return: { summary, category, severity (1-5), entities: {people, countries, organizations}, tags[], related_context }
  ```
- [ ] Model fallback: primary fails → retry with `AI_MODEL_FALLBACK`
- [ ] Response validation: reject malformed JSON, log and skip
- [ ] Rate limiting: configurable via `AI_MAX_REQUESTS_PER_MINUTE`
- [ ] Priority queue: geocoding first (so events appear on map fast), enrichment second
- [ ] Cost tracking: log model + token usage per call
- [ ] Graceful degradation: no API key = no enrichment, events stored raw
- [ ] Caches results — don't re-analyze same source_id
- [ ] `/api/ai/status` endpoint:
  ```json
  {
    "enabled": true,
    "provider": "openrouter",
    "primary_model": "google/gemini-2.5-flash-preview",
    "fallback_model": "deepseek/deepseek-chat-v3-0324",
    "events_enriched_today": 342,
    "events_geocoded_today": 89,
    "avg_latency_ms": 1200
  }
  ```
- [ ] Logs: `"AI [google/gemini-2.5-flash-preview]: geocoded 12 + enriched 8 events (3,400 tokens) in 6.2s"`

#### Technical Notes
```python
import httpx, json
from app.config import settings

class AIAnalyzer:
    """AI event analysis via OpenRouter. Model configurable via AI_MODEL env var."""
    
    def __init__(self):
        self.base_url = settings.openrouter_base_url
        self.api_key = settings.openrouter_api_key
        self.model = settings.ai_model
        self.fallback_model = settings.ai_model_fallback
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def _call_model(self, messages: list, model: str = None) -> dict:
        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://nexus-globe.app",
                "X-Title": "NEXUS GLOBE OSINT",
            },
            json={
                "model": model or self.model,
                "messages": messages,
                "max_tokens": settings.ai_max_tokens,
                "temperature": settings.ai_temperature,
                "response_format": {"type": "json_object"},
            }
        )
        response.raise_for_status()
        return response.json()
    
    async def geocode_event(self, event) -> dict:
        """Geocode an event that has no lat/lng (e.g., from RSS)."""
        messages = [
            {"role": "system", "content": "You are a geolocation expert. Return ONLY valid JSON."},
            {"role": "user", "content": f"Where is this event?\nTitle: {event.title}\nDescription: {event.description}\n\nReturn: {{\"latitude\": float, \"longitude\": float, \"location_name\": str, \"confidence\": 0-1}}"}
        ]
        try:
            data = await self._call_model(messages)
            geo = json.loads(data["choices"][0]["message"]["content"])
            if geo.get("latitude") and geo.get("confidence", 0) > 0.5:
                event.latitude = geo["latitude"]
                event.longitude = geo["longitude"]
                event.metadata["ai_geocoded"] = True
                event.metadata["location_name"] = geo.get("location_name", "")
                event.metadata["geocode_confidence"] = geo["confidence"]
        except Exception as e:
            logger.warning(f"AI geocoding failed: {e}")
        return event
    
    async def enrich_event(self, event) -> dict:
        """Full AI enrichment with fallback."""
        # ... (same pattern as before, with primary + fallback model)
```

#### Config Updates
```python
class Settings(BaseSettings):
    # AI (OpenRouter)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    ai_model: str = "google/gemini-2.5-flash-preview"
    ai_model_fallback: str = "deepseek/deepseek-chat-v3-0324"
    ai_max_tokens: int = 500
    ai_temperature: float = 0.3
    ai_max_requests_per_minute: int = 30
    
    # Event Registry
    event_registry_api_key: str = ""
```

#### Files to Create/Modify
- `backend/app/services/ai_analyzer.py`
- `backend/app/services/ingestion/rss_wires.py` (call geocode after normalization)
- `backend/app/services/ingestion/gdelt.py` (call enrichment)
- `backend/app/config.py` (add OpenRouter + Event Registry settings)
- `backend/app/api/routes.py` (add /api/ai/status)
- `backend/requirements.txt` (remove `anthropic`, add `feedparser`)
- `.env.example` (update with OpenRouter + Event Registry keys)

---

### STORY 2.9 — Scheduler Updates: Multi-Service Registration
**Track:** Backend
**Points:** 2
**Priority:** P1 — Important

#### Description
Update APScheduler to register all 7 ingestion services with their respective poll intervals.

#### Acceptance Criteria
- [ ] Scheduler registers all services:
  - RSS Wires: 30s, Event Registry: 120s, GDELT: 60s
  - OpenSky: 10s, USGS: 60s, EONET: 300s, AISHub: 60s
- [ ] Services with missing API keys skipped with warning
- [ ] Each service runs independently
- [ ] Startup log:
  ```
  Scheduler: Registered 7 services
    ✓ rss_wires       (interval: 30s)   — Tier 1 Fast
    ✓ event_registry  (interval: 120s)  — Tier 2 Smart
    ✓ gdelt           (interval: 60s)   — Tier 3 Deep
    ✓ opensky         (interval: 10s)
    ✓ usgs            (interval: 60s)
    ✓ eonet           (interval: 300s)
    ⚠ aishub          (interval: 60s)   — API key missing
  ```
- [ ] `/api/services` endpoint returns status of all services

#### Files to Create/Modify
- `backend/app/scheduler.py`
- `backend/app/api/routes.py` (add /api/services)

---

### STORY 2.10 — News Layer Rendering (Frontend)
**Track:** Frontend
**Points:** 5
**Priority:** P0 — Core Feature

#### Description
Render news events from all three tiers as pulsing cyan dots with ripple animations. Multi-source confirmed events pulse brighter.

#### Acceptance Criteria
- [ ] News events render as circular markers, color: neon cyan `#00f0ff`
- [ ] Size scales with severity (1 = small, 5 = large)
- [ ] Pulsing ripple animation: frequency tied to severity
- [ ] **Multi-source events pulse brighter** — if `metadata.confirmation_count > 2`, glow intensity increases
- [ ] "BREAKING" badge on events with `metadata.first_source` from Tier 1 (RSS) and age < 15 min
- [ ] Hover tooltip: title + source + confirmed by X sources + time ago + severity badge
- [ ] Click detail panel shows:
  - AI summary (if enriched), category + severity badge
  - Source link, related entities as tags
  - "Confirmed by: Reuters, BBC, GDELT" list if multi-source
  - "Analyzed by {model_name}" badge
  - Geocoding confidence indicator (for AI-geocoded events)
- [ ] Layer toggleable, handles 500+ markers at 60 FPS
- [ ] Events fade as they age

#### Files to Create/Modify
- `frontend/src/components/Globe/layers/NewsLayer.tsx`
- `frontend/src/components/Globe/GlobeCanvas.tsx`
- `frontend/src/components/Panel/EventDetail.tsx`

---

### STORY 2.11 — Disaster Layer Rendering (Frontend)
**Track:** Frontend
**Points:** 5
**Priority:** P0 — Core Feature

#### Description
Render earthquakes, wildfires, storms as dramatic expanding rings and flickering effects.

#### Acceptance Criteria
- [ ] **Earthquakes**: concentric expanding red rings (`#ff2244`), count = severity, speed ∝ magnitude
- [ ] **Wildfires**: flickering red-orange dot (`#ff2244` ↔ `#ff6600`), position jitter
- [ ] **Storms**: semi-transparent circle with trail path (dotted line if trail data)
- [ ] **Volcanoes**: pulsing red dot, larger than quake markers
- [ ] **Floods**: blue-tinted expanding area (`#2244ff`, low opacity)
- [ ] Hover: event name + magnitude/category + time + depth
- [ ] Click: detail panel with full USGS/EONET data + link
- [ ] Older events more transparent, layer toggleable, handles 100+ at 60 FPS

#### Files to Create/Modify
- `frontend/src/components/Globe/layers/DisasterLayer.tsx`
- `frontend/src/components/Globe/GlobeCanvas.tsx`

---

### STORY 2.12 — Ship Layer Rendering (Frontend)
**Track:** Frontend
**Points:** 5
**Priority:** P0 — Core Feature

#### Description
Render ship positions as green diamond markers with heading arrows and fading route trails.

#### Acceptance Criteria
- [ ] Diamond-shaped markers, color: neon green `#00ff88`
- [ ] Rotated to heading, sized by ship type (cargo/tanker larger, fishing smaller)
- [ ] Trail: thin green line of last 20 positions, fading at tail
- [ ] Hover: ship name, type, speed (kts), destination, flag
- [ ] Click: full AIS data (MMSI, IMO, type, speed, heading, destination, ETA, dimensions, flag, MarineTraffic link)
- [ ] Ships < 0.5 kts shown dimmed (at anchor)
- [ ] Shipping lanes visible as dense green corridors when zoomed out
- [ ] Layer toggleable, handles 3000+ at 60 FPS

#### Files to Create/Modify
- `frontend/src/components/Globe/layers/ShipLayer.tsx`
- `frontend/src/components/Globe/GlobeCanvas.tsx`

---

### STORY 2.13 — News Ticker Component
**Track:** Frontend
**Points:** 3
**Priority:** P2 — Polish

#### Description
Scrolling news ticker bar at the bottom displaying latest headlines from all three news tiers.

#### Acceptance Criteria
- [ ] Horizontal bar fixed at bottom, smooth CSS scroll right-to-left
- [ ] Shows latest 20 news events by timestamp
- [ ] Each headline: severity dot + category tag + title + time ago + source badge (Reuters/BBC/etc.)
- [ ] **"BREAKING" prefix** on events less than 15 min old from Tier 1 RSS
- [ ] **Multi-source indicator**: "✓✓✓" dots showing how many sources confirmed
- [ ] Click headline → fly camera to location + open detail panel
- [ ] Pauses on hover, new headlines flash/glow on entry
- [ ] Cyberpunk styling: `--bg-panel` blur, `--font-mono` cyan, top border glow
- [ ] "NO ACTIVE FEEDS" when empty

#### Files to Create/Modify
- `frontend/src/components/HUD/NewsTicker.tsx`
- `frontend/src/styles/cyberpunk.css`
- `frontend/src/App.tsx`

---

### STORY 2.14 — Layer Controls & HUD Updates
**Track:** Frontend
**Points:** 3
**Priority:** P1 — Important

#### Description
Update layer controls and HUD to show all 4 active layers, news source tiers, and AI status.

#### Acceptance Criteria
- [ ] Layer controls: ✈️ Flights, 📰 News, 🌋 Disasters, 🚢 Ships (all active with counts)
- [ ] Remaining layers dimmed: 🛰️ Satellites, ⚔️ Conflicts, 🚗 Traffic, 📹 Cameras — "Coming soon"
- [ ] HUD stats: `✈ 4,832 | 📰 47 | 🌋 12 | 🚢 2,847` (color-coded, animated)
- [ ] **News source breakdown** (expandable): `📰 47 (12 RSS • 23 ER • 12 GDELT)`
- [ ] HUD shows "INTEL FEEDS: 4/8 ACTIVE" + "NEWS TIERS: 3/3 ONLINE"
- [ ] HUD AI status: "AI: K2.5 via OpenRouter ●" (green/red based on `/api/ai/status`)
- [ ] Keyboard shortcuts: `1`-`4` toggle layers
- [ ] Toggle triggers WS subscribe/unsubscribe, animates glow on/off

#### Files to Create/Modify
- `frontend/src/components/Controls/LayerControls.tsx`
- `frontend/src/components/Controls/LayerToggle.tsx`
- `frontend/src/components/HUD/LiveStats.tsx`
- `frontend/src/components/HUD/HUDOverlay.tsx`

---

## Story Dependency Graph

```mermaid
graph TD
    E1[Epic 1 Complete<br/>Globe + Flights + WS]

    S1[2.1 RSS Wires<br/>Tier 1 Fast]
    S2[2.2 Event Registry<br/>Tier 2 Smart]
    S3[2.3 GDELT<br/>Tier 3 Deep]
    S4[2.4 USGS Quakes]
    S5[2.5 NASA EONET]
    S6[2.6 AISHub Ships]
    S7[2.7 Dedup Engine]
    S8[2.8 OpenRouter AI]
    S9[2.9 Scheduler]
    S10[2.10 News Layer UI]
    S11[2.11 Disaster Layer UI]
    S12[2.12 Ship Layer UI]
    S13[2.13 News Ticker]
    S14[2.14 HUD Update]

    E1 --> S1 & S2 & S3 & S4 & S5 & S6
    S1 --> S7
    S2 --> S7
    S3 --> S7
    S1 --> S8
    S7 --> S8
    S4 & S5 & S6 --> S7
    S8 --> S9
    S7 --> S9
    S8 --> S10
    S1 & S2 & S3 --> S10
    S4 & S5 --> S11
    S6 --> S12
    S10 --> S13
    S10 & S11 & S12 --> S14

    style E1 fill:#666,color:#fff
    style S1 fill:#ff2244,color:#fff
    style S2 fill:#ff6600,color:#fff
    style S3 fill:#00f0ff,color:#000
    style S4 fill:#ff2244,color:#fff
    style S5 fill:#ff2244,color:#fff
    style S6 fill:#00ff88,color:#000
    style S7 fill:#ffee00,color:#000
    style S8 fill:#ff00aa,color:#fff
    style S9 fill:#ffee00,color:#000
    style S10 fill:#00f0ff,color:#000
    style S11 fill:#ff2244,color:#fff
    style S12 fill:#00ff88,color:#000
    style S13 fill:#00f0ff,color:#000
    style S14 fill:#ffee00,color:#000
```

**Legend:** 🔴 Tier 1 Fast → 🟠 Tier 2 Smart → 🔵 Tier 3 Deep → 🟢 Ships → 🟣 AI → 🟡 Integration

---

## Suggested Work Order

| Day | Backend Developer | Frontend Developer |
|-----|-------------------|--------------------|
| 1 | 2.1 RSS Wire Ingestion | 2.10 News Layer UI (mock data) |
| 2 | 2.2 Event Registry | 2.11 Disaster Layer UI (mock data) |
| 3 | 2.3 GDELT + 2.4 USGS | 2.12 Ship Layer UI (mock data) |
| 4 | 2.5 EONET + 2.6 AISHub | 2.13 News Ticker |
| 5 | 2.7 Dedup Engine | Connect layers to live WebSocket data |
| 6 | 2.8 OpenRouter AI Analyzer | 2.14 Layer Controls + HUD |
| 7 | 2.9 Scheduler + Integration | End-to-end testing |
| 8 | End-to-end testing | Polish & bug fixes |

Solo order: 2.1 → 2.2 → 2.3 → 2.4 → 2.5 → 2.7 → 2.8 → 2.6 → 2.9 → 2.10 → 2.11 → 2.12 → 2.13 → 2.14

---

## Updated .env.example

```env
# === DATABASE ===
DATABASE_URL=postgresql+asyncpg://nexus:nexus@localhost:5432/nexus
REDIS_URL=redis://localhost:6379

# === AI CONFIGURATION (OpenRouter) ===
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxx
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
AI_MODEL=google/gemini-2.5-flash-preview
AI_MODEL_FALLBACK=deepseek/deepseek-chat-v3-0324
AI_MAX_TOKENS=500
AI_TEMPERATURE=0.3
AI_MAX_REQUESTS_PER_MINUTE=30

# === NEWS SOURCES ===
EVENT_REGISTRY_API_KEY=                  # Free tier: eventregistry.org/register

# === DATA SOURCE API KEYS ===
GOOGLE_MAPS_API_KEY=AIza...
OPENSKY_USERNAME=
OPENSKY_PASSWORD=
AISHUB_API_KEY=
ACLED_API_KEY=
ACLED_EMAIL=
```

---

## Updated requirements.txt Changes

```diff
- anthropic==0.37.0
+ feedparser==6.0.11
# httpx already included — handles OpenRouter + all API calls
```

---

## Testing Checklist

### Backend — News Pipeline Tests
- [ ] RSS feeds return valid articles from at least 3/6 sources
- [ ] RSS events flagged with `needs_geocoding: true`
- [ ] Event Registry returns geocoded, categorized events
- [ ] Event Registry skips gracefully without API key
- [ ] GDELT returns valid geocoded articles
- [ ] Same story from Reuters RSS + BBC RSS → merged (not duplicated)
- [ ] Same event from RSS + Event Registry + GDELT → single event with 3 confirmations
- [ ] `metadata.confirmed_by` array correctly tracks all sources
- [ ] OpenRouter AI geocodes RSS events with > 70% accuracy
- [ ] OpenRouter AI enriches events with summary + severity + entities
- [ ] AI model specified in `AI_MODEL` env var is actually used
- [ ] AI fallback triggers when primary model fails
- [ ] AI handles missing API key gracefully
- [ ] Batch enrichment processes 5 events per API call
- [ ] `/api/ai/status` returns correct model info

### Backend — Other Layer Tests
- [ ] USGS earthquakes ingested correctly
- [ ] EONET events ingested with trail data for storms
- [ ] AISHub ships ingested, deduped by MMSI
- [ ] All 7 services run concurrently via scheduler
- [ ] Event expiry cleanup works

### Frontend Tests
- [ ] News markers: cyan pulsing dots, multi-source events pulse brighter
- [ ] "BREAKING" badge on recent Tier 1 events
- [ ] Earthquake markers: expanding red rings
- [ ] Ship markers: green diamonds with heading
- [ ] All layers toggle on/off correctly
- [ ] News ticker scrolls with source badges and confirmation dots
- [ ] Clicking ticker → camera fly-to + detail panel
- [ ] Detail panel shows AI summary + "Analyzed by {model}" + "Confirmed by: Reuters, BBC"
- [ ] HUD shows news tier breakdown (RSS • ER • GDELT)
- [ ] HUD shows AI status with model name
- [ ] Keyboard shortcuts 1-4 work
- [ ] Performance: 8500+ total markers at 30+ FPS

### End-to-End Smoke Test
```
1.  docker-compose up
2.  Open localhost:5173
3.  Globe shows flights (Epic 1 still working)             ✓
4.  Cyan news dots appear within 2 minutes (RSS Tier 1)    ✓
5.  More news dots fill in over 15 min (ER + GDELT)        ✓
6.  Multi-source events pulse brighter                      ✓
7.  "BREAKING" badge visible on fresh headlines             ✓
8.  Red expanding rings appear (earthquakes)                ✓
9.  Green diamonds on shipping lanes (ships)                ✓
10. News ticker scrolls with source badges                  ✓
11. Click news → AI summary + "Confirmed by 3 sources"     ✓
12. Click earthquake → magnitude + depth                    ✓
13. Click ship → name, type, destination                    ✓
14. HUD: "📰 47 (12 RSS • 23 ER • 12 GDELT)"             ✓
15. HUD: "AI: K2.5 via OpenRouter ●"                       ✓
16. Toggle layers 1-4 with keyboard                         ✓
17. All 4 layers visible at 30+ FPS                         ✓
```

---

## API Keys Required for This Epic

| Service | Key | How to Get | Required? |
|---------|-----|-----------|-----------|
| **OpenRouter** | `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) — free tier | Recommended (AI degrades gracefully without) |
| **Event Registry** | `EVENT_REGISTRY_API_KEY` | [eventregistry.org/register](https://eventregistry.org/register) — free 200 req/day | Optional (Tier 2 disabled without) |
| **AISHub** | `AISHUB_API_KEY` | [aishub.net/register](http://www.aishub.net/register) — free | Optional (ships disabled without) |
| RSS Feeds | None | Free, no auth | — |
| GDELT | None | Free, no auth | — |
| USGS | None | Free, no auth | — |
| NASA EONET | None | Free, no auth | — |

---

## Definition of Done — Epic Complete When:

1. **Three-tier news pipeline** active: RSS (fast) + Event Registry (smart) + GDELT (deep)
2. Breaking news from RSS appears on globe within **5 minutes** of publishing
3. Multi-source events show confirmation count and pulse brighter
4. "BREAKING" badge visible on fresh Tier 1 headlines
5. USGS earthquakes + EONET disasters render as red expanding rings
6. AIS ships render as green diamonds with route trails
7. Cross-source deduplication merges same story from multiple feeds
8. **OpenRouter AI** geocodes RSS events and enriches all news with summaries
9. AI model configurable via `AI_MODEL` env var, fallback works automatically
10. News ticker scrolls with source badges and confirmation indicators
11. HUD shows per-tier news breakdown + AI status with model name
12. Layer controls with real-time counts + keyboard shortcuts 1-4
13. Performance: 8500+ total markers at 30+ FPS
14. No console errors, graceful handling of missing API keys
15. **No Anthropic SDK dependency** — all AI through OpenRouter httpx calls

---

*Epic 2 of 5 — NEXUS GLOBE*
*Estimated effort: 58 story points | 8 working days (solo) | 5 days (pair)*
*Dependencies: Epic 1 complete*