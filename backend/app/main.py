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
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import accuracy, auth, buoys, cache, config, forecast, sessions
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
    sessions.init_db()

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


# --- Access gate (see auth.py) --------------------------------------------
# Paths reachable WITHOUT passing the gate: the gate API itself, health, and
# static assets (so the gate page can render). Everything else — the data API
# and the app routes — requires a valid session cookie.
_GATE_OPEN_PREFIXES = ("/api/gate", "/api/health", "/_app", "/favicon", "/fonts")


def _client_ip(request: Request) -> str:
    """Client IP for rate-limiting.

    X-Forwarded-For is client-controllable, so trusting it blindly lets an
    attacker spoof a fresh IP per request and dodge the lockout. Only honour XFF
    when the DIRECT connection is a trusted proxy (config.TRUSTED_PROXIES), and
    take the LAST hop XFF added (the proxy's view of the real client), not the
    first (which the client can inject). Otherwise use the direct peer IP.
    """
    peer = request.client.host if request.client else "unknown"
    if peer in config.TRUSTED_PROXIES:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            hops = [h.strip() for h in xff.split(",") if h.strip()]
            if hops:
                return hops[-1]
    return peer


@app.middleware("http")
async def gate_middleware(request: Request, call_next):
    if not auth.GATE_ENABLED:
        return await call_next(request)

    path = request.url.path
    if any(path == p or path.startswith(p) for p in _GATE_OPEN_PREFIXES):
        return await call_next(request)

    token = request.cookies.get(auth.COOKIE_NAME)
    if auth.verify_token(token):
        return await call_next(request)

    # Not authorised. For API calls return 401 JSON; for page loads send the
    # SPA (it will show the gate screen based on the failing /api/gate/status).
    if path.startswith("/api/"):
        return JSONResponse({"detail": "gate: not authorised"}, status_code=401)
    return await call_next(request)  # SPA renders the gate view client-side


@app.get("/api/gate/status")
def gate_status(request: Request):
    token = request.cookies.get(auth.COOKIE_NAME)
    locked, remaining = auth.is_locked(_client_ip(request))
    return {
        "enabled": auth.GATE_ENABLED,
        "authorised": auth.verify_token(token),
        "question": auth.GATE_QUESTION,
        "locked": locked,
        "lockout_remaining_s": remaining,
        "max_tries": auth.GATE_MAX_TRIES,
    }


@app.post("/api/gate/answer")
async def gate_answer(request: Request):
    ip = _client_ip(request)
    locked, remaining = auth.is_locked(ip)
    if locked:
        return JSONResponse(
            {"ok": False, "locked": True, "lockout_remaining_s": remaining},
            status_code=429,
        )
    body = await request.json()
    if auth.check_answer(body.get("answer", "")):
        auth.clear(ip)
        resp = JSONResponse({"ok": True})
        resp.set_cookie(
            auth.COOKIE_NAME, auth.issue_token(),
            max_age=auth.GATE_SESSION_S, httponly=True, samesite="lax",
            secure=config.COOKIE_SECURE,
        )
        return resp
    remaining_tries = auth.register_failure(ip)
    locked, lock_remaining = auth.is_locked(ip)
    return JSONResponse(
        {"ok": False, "tries_remaining": remaining_tries,
         "locked": locked, "lockout_remaining_s": lock_remaining},
        status_code=401,
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/spots")
def spots():
    return {"spots": [forecast.spot_meta(s) for s in load_spots()]}


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


@app.get("/api/buoys")
def buoy_readings():
    """Live measured offshore conditions from Marine Institute buoys."""
    return {"buoys": buoys.latest_readings()}


@app.get("/api/accuracy")
def accuracy_scorecard():
    """Which forecast model has been most accurate vs measured buoys lately."""
    return accuracy.build_scorecard()


@app.get("/api/sessions")
def list_sessions(spot_id: str | None = Query(None)):
    return {"sessions": sessions.list_for(spot_id)}


@app.post("/api/sessions")
async def add_session(request: Request):
    body = await request.json()
    spot_id = body.get("spot_id")
    if not spot_id or get_spot(spot_id) is None:
        raise HTTPException(status_code=400, detail="valid spot_id required")
    date = body.get("date") or ""
    try:
        rating = int(body.get("rating"))
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail="rating 0-5 required") from e
    return sessions.add(spot_id, date, rating, body.get("notes", ""))


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: int):
    if not sessions.delete(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return {"ok": True}


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
