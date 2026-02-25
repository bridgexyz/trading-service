"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.database import create_db_and_tables
from backend.utils.logging import setup_logging
from backend.api import auth, pairs, credentials, trades, positions, dashboard, system, markets


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    setup_logging()
    create_db_and_tables()
    # Sync DB positions against exchange state before starting jobs
    from backend.engine.position_sync import sync_positions_on_startup
    await sync_positions_on_startup()
    from backend.engine.scheduler import start_scheduler, stop_scheduler
    start_scheduler()

    # Start Telegram bot if configured
    telegram_bot = None
    if settings.telegram_bot_token:
        from backend.services.telegram_bot import init_bot
        telegram_bot = init_bot()
        telegram_bot.start()

    yield

    if telegram_bot:
        telegram_bot.stop()
    stop_scheduler()


app = FastAPI(
    title="Trading Service",
    description="Lighter DEX pair trading service with admin panel",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(auth.router)
app.include_router(pairs.router)
app.include_router(credentials.router)
app.include_router(trades.router)
app.include_router(positions.router)
app.include_router(dashboard.router)
app.include_router(system.router)
app.include_router(markets.router)

# Serve frontend static files in production (must be after all API routers).
# Skip when CORS origins include localhost dev server (i.e. Vite is running separately).
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
_is_dev = any("localhost" in o or "127.0.0.1" in o for o in settings.cors_origins)
if _frontend_dist.exists() and not _is_dev:
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="static-assets")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        file = _frontend_dist / path
        if file.is_file():
            return FileResponse(str(file))
        return FileResponse(str(_frontend_dist / "index.html"))
