"""Application configuration, sourced from environment variables.

All settings have sensible defaults so the app runs with zero config on a home
server; Docker Compose overrides them via environment (see docs/SDD.md §12).
"""

from __future__ import annotations

import os
from pathlib import Path

# Repo layout: backend/app/config.py -> project root is two parents up from app/
_APP_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _APP_DIR.parent
_PROJECT_ROOT = _BACKEND_DIR.parent

# Data directory (spots.json + SQLite). Mounted as a volume in Docker.
DATA_DIR = Path(os.environ.get("DATA_DIR", _PROJECT_ROOT / "data"))
SPOTS_FILE = Path(os.environ.get("SPOTS_FILE", DATA_DIR / "spots.json"))
DB_PATH = Path(os.environ.get("DB_PATH", DATA_DIR / "waveometer.sqlite3"))

# Forecast horizon (days). SDD §2/§8: 12-day outlook.
FORECAST_DAYS = int(os.environ.get("FORECAST_DAYS", "12"))

# Refresh behaviour (SDD §5).
CACHE_STALE_MIN = int(os.environ.get("CACHE_STALE_MIN", "60"))
REFRESH_INTERVAL_MIN = int(os.environ.get("REFRESH_INTERVAL_MIN", "360"))

# Open-Meteo endpoints (no API key required).
MARINE_API = os.environ.get(
    "MARINE_API", "https://marine-api.open-meteo.com/v1/marine"
)
FORECAST_API = os.environ.get(
    "FORECAST_API", "https://api.open-meteo.com/v1/forecast"
)

# Wave models (SDD §4/§8). ECMWF is primary; GWAM/EWAM add the confidence spread.
# GWAM dropped: its coarse global grid resolves nearshore Irish points onto
# land (~0.5 m at Lahinch while ECMWF/others read ~2.3 m), poisoning the spread.
# meteofrance_wave resolves the coast well and reaches ~day 10.
PRIMARY_WAVE_MODEL = "ecmwf_wam025"
# Spread models for the confidence signal: meteofrance_wave (~day 10) + ewam
# (~day 3). GWAM is deliberately excluded — re-verified that its coarse grid
# still resolves nearshore Irish spots onto land (0.59 m at Lahinch vs ~3 m),
# which poisons the spread. Only ECMWF is trusted for the rating itself.
SPREAD_WAVE_MODELS = ["meteofrance_wave", "ewam"]
ALL_WAVE_MODELS = [PRIMARY_WAVE_MODEL, *SPREAD_WAVE_MODELS]

# HTTP behaviour.
HTTP_TIMEOUT_S = int(os.environ.get("HTTP_TIMEOUT_S", "30"))
HTTP_RETRIES = int(os.environ.get("HTTP_RETRIES", "3"))
HTTP_RETRY_BACKOFF_S = float(os.environ.get("HTTP_RETRY_BACKOFF_S", "1.5"))

# How many spots to refresh in parallel (each spot = 3 concurrent calls).
REFRESH_CONCURRENCY = int(os.environ.get("REFRESH_CONCURRENCY", "5"))

# Force IPv4 for upstream requests. Default on: many WSL/home-server setups
# resolve Open-Meteo to IPv6 but have no IPv6 route ("Network is unreachable").
FORCE_IPV4 = os.environ.get("FORCE_IPV4", "1") not in ("0", "false", "False")

# CORS: prod serves the SPA same-origin so none is strictly needed; these cover
# the Vite dev server. Override with CORS_ORIGINS="https://host" (comma-sep).
CORS_ORIGINS = [
    o.strip() for o in os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",") if o.strip()
]

# Gate cookie Secure flag (send only over HTTPS). Defaults ON — safer for a
# public deployment; set COOKIE_SECURE=0 only for local plain-http dev.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") not in ("0", "false", "False")

# Reverse proxies whose X-Forwarded-For we trust for client-IP rate limiting.
# Empty by default (use the direct peer IP). Set to your proxy's IP(s),
# comma-separated, e.g. TRUSTED_PROXIES="127.0.0.1,172.18.0.1".
TRUSTED_PROXIES = {
    p.strip() for p in os.environ.get("TRUSTED_PROXIES", "").split(",") if p.strip()
}

# County display order for the home page (SDD §11): Clare first.
COUNTY_ORDER = ["Clare", "Sligo", "Mayo", "Kerry"]

# All spots are in Ireland; fetch forecasts in Irish local time so displayed
# hours are DST-correct (IST = UTC+1 in summer). Buoy validation stays UTC.
TIMEZONE = os.environ.get("TIMEZONE", "Europe/Dublin")
