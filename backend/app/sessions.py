"""Surf session logging (SDD §13 — the calibration foundation).

Log what you ACTUALLY observed when you surfed: spot, date, your 0–5 rating, and
notes. Over time this is the one dataset that can genuinely beat commercial apps
for these spots — comparing your observed rating against what the model predicted
lets the app learn local corrections. v1 just stores + lists them; the
calibration step builds on this later.
"""

from __future__ import annotations

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
            CREATE TABLE IF NOT EXISTS sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                spot_id     TEXT NOT NULL,
                date        TEXT NOT NULL,          -- YYYY-MM-DD (surf date)
                rating      INTEGER NOT NULL,       -- observed 0-5
                notes       TEXT DEFAULT '',
                created_at  TEXT NOT NULL
            )
            """
        )


def add(spot_id: str, date: str, rating: int, notes: str = "") -> dict:
    rating = max(0, min(5, int(rating)))
    created = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (spot_id, date, rating, notes, created_at) "
            "VALUES (?,?,?,?,?)",
            (spot_id, date, rating, notes.strip()[:500], created),
        )
        sid = cur.lastrowid
    return {"id": sid, "spot_id": spot_id, "date": date,
            "rating": rating, "notes": notes.strip()[:500], "created_at": created}


def list_for(spot_id: str | None = None, limit: int = 100) -> list[dict]:
    with _lock, _connect() as conn:
        if spot_id:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE spot_id=? ORDER BY date DESC, id DESC "
                "LIMIT ?", (spot_id, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY date DESC, id DESC LIMIT ?",
                (limit,)).fetchall()
    return [dict(r) for r in rows]


def delete(session_id: int) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        return cur.rowcount > 0
