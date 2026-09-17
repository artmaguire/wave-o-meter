"""SQLite forecast cache (SDD 5, 9).

Stores the scored hourly forecast per spot as a JSON blob plus a fetched_at
timestamp. Supports the two-layer refresh strategy:
  - on-open: is_stale() drives a refresh if older than CACHE_STALE_MIN
  - scheduler: refresh_all() called periodically

Storing the computed forecast (not just raw model data) keeps reads cheap: the
API serves cached JSON directly and only recomputes on refresh.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS forecast_cache (
                spot_id     TEXT PRIMARY KEY,
                fetched_at  TEXT NOT NULL,
                payload     TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_accuracy (
                buoy    TEXT NOT NULL,
                model   TEXT NOT NULL,
                window  TEXT NOT NULL,
                mae     REAL, rmse REAL, corr REAL,
                PRIMARY KEY (buoy, model, window)
            )
            """
        )


def get(spot_id: str) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT fetched_at, payload FROM forecast_cache WHERE spot_id=?",
            (spot_id,),
        ).fetchone()
    if not row:
        return None
    return {"fetched_at": row["fetched_at"], "payload": json.loads(row["payload"])}


def put(spot_id: str, payload: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO forecast_cache (spot_id, fetched_at, payload) "
            "VALUES (?,?,?) ON CONFLICT(spot_id) DO UPDATE SET "
            "fetched_at=excluded.fetched_at, payload=excluded.payload",
            (spot_id, now, json.dumps(payload)),
        )


def fetched_at(spot_id: str) -> datetime | None:
    entry = get(spot_id)
    if not entry:
        return None
    return datetime.fromisoformat(entry["fetched_at"])


def is_stale(spot_id: str) -> bool:
    ts = fetched_at(spot_id)
    if ts is None:
        return True
    age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60.0
    return age_min >= config.CACHE_STALE_MIN
