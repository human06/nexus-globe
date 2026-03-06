# Nexus Globe

A real-time global intelligence dashboard visualising live data streams — flights, ships, satellites, earthquakes, disasters, conflicts, and news events — rendered on an interactive 3D globe with a cyberpunk aesthetic.

## Stack

- **Frontend**: React 19 + TypeScript + Vite, Globe.GL, Zustand, Tailwind CSS v4, Framer Motion
- **Backend**: Python FastAPI with async SQLAlchemy, APScheduler, Anthropic Claude AI
- **Database**: PostgreSQL 16 + PostGIS
- **Cache/Pub-Sub**: Redis 7

## Setup

### Prerequisites

- Docker & Docker Compose
- Node.js 20+ (for local frontend dev)
- Python 3.12+ (for local backend dev)

### Quick Start with Docker

```bash
# 1. Clone repo and navigate to project root
cd nexus-globe

# 2. Copy env template and fill in your API keys
cp .env.example .env

# 3. Start all services
docker-compose up
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

### Local Development

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

**Backend:**
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Data Sources

| Layer | Source | Update Interval |
|-------|--------|-----------------|
| Flights | OpenSky Network | 15s |
| Ships | AISHub | 30s |
| Satellites | CelesTrak | 60s |
| Earthquakes | USGS | 60s |
| Disasters | NASA EONET | 5m |
| Conflicts | ACLED | 1h |
| News | GDELT | 5m |

## Environment Variables

See `.env.example` for all required keys.
