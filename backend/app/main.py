"""Wave-o-meter FastAPI app (SDD 5, 10, 12).

Endpoints:
  GET /api/health
  GET /api/spots                     -> spot metadata, county-ordered
  GET /api/overview                  -> home page (current rating per spot)
  GET /api/spots/{id}/forecast       -> full 12-day hourly forecast
  GET /api/accuracy                  -> model-accuracy scorecard (placeholder)

A background scheduler refreshes the cache every REFRESH_INTERVAL_MIN; individual
reads also refresh on staleness (on-open behaviour).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import cache, config, forecast
from .spots import get_spot, load_spots

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("waveometer.main")

_scheduler: BackgroundScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache.init_db()

    global _scheduler
    _scheduler = BackgroundScheduler(daemon=True)
    # Warm the cache in the scheduler thread (not inline) so the app becomes
    # ready immediately instead of blocking on ~20 upstream calls. Reads that
    # arrive before warm-up completes refresh on demand (on-open behaviour).
    _scheduler.add_job(forecast.refresh_all, "date", id="warmup")
    _scheduler.add_job(
        forecast.refresh_all,
        "interval",
        minutes=config.REFRESH_INTERVAL_MIN,
        id="refresh_all",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)


app = FastAPI(title="Wave-o-meter", version="0.1", lifespan=lifespan)

# In production the SvelteKit app is served by this same backend (same origin),
# so no cross-origin access is needed. CORS is only for local dev (Vite on :5173
# proxying to :8080). Default to an explicit dev allowlist rather than "*";
# override with CORS_ORIGINS (comma-separated) if needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/spots")
def spots():
    return {"spots": [forecast._spot_meta(s) for s in load_spots()]}


@app.get("/api/overview")
def overview():
    return forecast.build_overview()


@app.get("/api/spots/{spot_id}/forecast")
def spot_forecast(spot_id: str, force: bool = Query(False)):
    spot = get_spot(spot_id)
    if not spot:
        raise HTTPException(status_code=404, detail=f"unknown spot: {spot_id}")
    return forecast.get_forecast(spot, force=force)


@app.get("/api/summary")
def summary():
    return forecast.build_summary()


@app.get("/api/accuracy")
def accuracy():
    # Placeholder until the buoy-validation job is ported from the spike.
    return {"models": [], "note": "model-accuracy scorecard not yet populated"}


# --- Serve the built SvelteKit SPA (SDD §12: single-container deploy) ---
# Mounted last so /api/* routes above take precedence. Static files are served
# directly; any unknown non-API path falls back to index.html so client-side
# routes (e.g. /spot/lahinch) work on deep-link / refresh.
_FRONTEND_BUILD = Path(
    os.environ.get(
        "FRONTEND_DIR",
        Path(__file__).resolve().parent.parent.parent / "frontend" / "build",
    )
)

if _FRONTEND_BUILD.is_dir():
    from fastapi.responses import FileResponse

    _ASSETS = _FRONTEND_BUILD / "_app"
    if _ASSETS.is_dir():
        app.mount("/_app", StaticFiles(directory=_ASSETS), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # never shadow the API
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (_FRONTEND_BUILD / full_path).resolve()
        # serve a real static file if it exists and is inside the build dir
        if (
            full_path
            and _FRONTEND_BUILD in candidate.parents
            and candidate.is_file()
        ):
            return FileResponse(candidate)
        # otherwise the SPA entrypoint (client-side routing takes over)
        return FileResponse(_FRONTEND_BUILD / "index.html")
