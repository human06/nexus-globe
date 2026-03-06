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
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # Handle subscribe / unsubscribe messages
            action = data.get("action")
            layer = data.get("layer")
            if action == "subscribe" and layer:
                await manager.subscribe(websocket, layer)
            elif action == "unsubscribe" and layer:
                await manager.unsubscribe(websocket, layer)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
