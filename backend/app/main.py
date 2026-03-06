"""FastAPI application entry point."""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.websockets import WebSocket, WebSocketDisconnect

from app.api.routes import router as api_router
from app.api.websocket import manager
from app.db.database import init_db
from app.db.redis import init_redis, close_redis
from app.scheduler import start_scheduler

logger = logging.getLogger(__name__)

# Module-level startup timestamp (seconds since epoch)
APP_START_TIME: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    global APP_START_TIME
    APP_START_TIME = time.time()
    logger.info("Nexus Globe backend starting…")
    await init_db()
    await init_redis()
    start_scheduler()
    yield
    logger.info("Nexus Globe backend shutting down…")
    await close_redis()


app = FastAPI(
    title="Nexus Globe API",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ───────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── REST routes ────────────────────────────────────────────────────────────────
app.include_router(api_router)


# ── WebSocket endpoint ─────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Real-time event stream.

    Client sends:
      { "action": "subscribe",   "layers": ["flight", "news"] }
      { "action": "unsubscribe", "layers": ["flight"] }
      { "action": "get_detail",  "event_id": "<uuid>" }

    Server pushes:
      { "type": "snapshot",     "data": [...] }
      { "type": "event_update", "data": {...} }
      { "type": "event_batch",  "data": [...] }
      { "type": "event_remove", "data": {"id": "..."} }
      { "type": "ping" }
    """
    await manager.connect(websocket)
    try:
        while True:
            try:
                data = await websocket.receive_json()
            except Exception:
                # Malformed message — log and skip
                logger.debug("Malformed WebSocket message, skipping")
                continue

            action = data.get("action")

            if action == "subscribe":
                layers = data.get("layers") or []
                if isinstance(layers, list) and layers:
                    await manager.subscribe(websocket, layers)

            elif action == "unsubscribe":
                layers = data.get("layers") or []
                if isinstance(layers, list) and layers:
                    await manager.unsubscribe(websocket, layers)

            elif action == "get_detail":
                # Placeholder — full detail lookup wired in later stories
                event_id = data.get("event_id")
                if event_id:
                    await manager.push(
                        websocket,
                        {"type": "error", "data": {"message": "get_detail not yet implemented"}},
                    )

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
