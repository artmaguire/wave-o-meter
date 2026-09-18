"""Surf session logging (SDD §13 — the calibration foundation).

Log what you ACTUALLY observed when you surfed. Over time this is the dataset
that can genuinely tune the forecast to these spots: comparing your observed
rating (and the conditions you saw) against what the model predicted for the
same hour lets us correct per-spot bias.

The schema is deliberately structured (dropdown-friendly) rather than freeform,
because consistent categorical values are what make later analysis possible —
with a free-text notes field kept for anything the fields can't capture.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import db

# --- controlled vocabularies (drive the UI dropdowns and validation) ---
RATINGS = [0, 1, 2, 3, 4, 5]
WAVE_SIZES = ["ankle", "knee", "waist", "chest", "shoulder", "head",
              "overhead", "double-overhead"]
WAVE_QUALITY = ["mushy", "soft", "workable", "clean", "punchy", "hollow"]
WIND_OBSERVED = ["glassy", "light offshore", "offshore", "cross-shore",
                 "light onshore", "onshore", "blown out"]
TIDE_OBSERVED = ["low", "low-mid", "mid", "mid-high", "high"]
TIDE_MOVEMENT = ["rising", "falling", "slack"]
CROWD = ["empty", "a few out", "moderate", "busy", "packed"]
BOARDS = ["shortboard", "fish", "mid-length", "longboard", "gun", "foamie",
          "bodyboard"]
WETSUITS = ["3/2", "4/3", "4/3 + booties", "5/4 hooded", "5/4/3 hooded"]
SESSION_LENGTH = ["<30 min", "30-60 min", "1-2 h", "2 h+"]

VOCAB = {
    "rating": RATINGS,
    "wave_size": WAVE_SIZES,
    "wave_quality": WAVE_QUALITY,
    "wind": WIND_OBSERVED,
    "tide": TIDE_OBSERVED,
    "tide_movement": TIDE_MOVEMENT,
    "crowd": CROWD,
    "board": BOARDS,
    "wetsuit": WETSUITS,
    "length": SESSION_LENGTH,
}

# Columns added after the first release — created on demand so existing rows
# (which only had spot_id/date/rating/notes) keep working.
_EXTRA_COLUMNS = {
    "time_of_day": "TEXT DEFAULT ''",     # e.g. "08:00" — which hour surfed
    "wave_size": "TEXT DEFAULT ''",
    "wave_quality": "TEXT DEFAULT ''",
    "wind": "TEXT DEFAULT ''",
    "tide": "TEXT DEFAULT ''",
    "tide_movement": "TEXT DEFAULT ''",
    "crowd": "TEXT DEFAULT ''",
    "board": "TEXT DEFAULT ''",
    "wetsuit": "TEXT DEFAULT ''",
    "length": "TEXT DEFAULT ''",
}

_FIELDS = ["spot_id", "date", "time_of_day", "rating", "wave_size",
           "wave_quality", "wind", "tide", "tide_movement", "crowd", "board",
           "wetsuit", "length", "notes"]


def init_db() -> None:
    with db.lock, db.connect() as conn:
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
        # migrate: add the richer columns if this DB predates them
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
        for col, decl in _EXTRA_COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {decl}")


def _clean(value, allowed: list, default: str = "") -> str:
    """Keep only known vocabulary values so the data stays analysable."""
    v = (value or "").strip()
    return v if v in allowed else default


def add(spot_id: str, date: str, rating: int, notes: str = "",
        **fields) -> dict:
    rating = max(0, min(5, int(rating)))
    row = {
        "spot_id": spot_id,
        "date": date,
        "time_of_day": (fields.get("time_of_day") or "").strip()[:5],
        "rating": rating,
        "wave_size": _clean(fields.get("wave_size"), WAVE_SIZES),
        "wave_quality": _clean(fields.get("wave_quality"), WAVE_QUALITY),
        "wind": _clean(fields.get("wind"), WIND_OBSERVED),
        "tide": _clean(fields.get("tide"), TIDE_OBSERVED),
        "tide_movement": _clean(fields.get("tide_movement"), TIDE_MOVEMENT),
        "crowd": _clean(fields.get("crowd"), CROWD),
        "board": _clean(fields.get("board"), BOARDS),
        "wetsuit": _clean(fields.get("wetsuit"), WETSUITS),
        "length": _clean(fields.get("length"), SESSION_LENGTH),
        "notes": (notes or "").strip()[:1000],
    }
    created = datetime.now(timezone.utc).isoformat()
    cols = ", ".join(_FIELDS) + ", created_at"
    marks = ", ".join(["?"] * (len(_FIELDS) + 1))
    with db.lock, db.connect() as conn:
        cur = conn.execute(
            f"INSERT INTO sessions ({cols}) VALUES ({marks})",
            [row[f] for f in _FIELDS] + [created],
        )
        sid = cur.lastrowid
    return {"id": sid, "created_at": created, **row}


def list_for(spot_id: str | None = None, limit: int = 200) -> list[dict]:
    with db.lock, db.connect() as conn:
        if spot_id:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE spot_id=? "
                "ORDER BY date DESC, id DESC LIMIT ?", (spot_id, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY date DESC, id DESC LIMIT ?",
                (limit,)).fetchall()
    return [dict(r) for r in rows]


def delete(session_id: int) -> bool:
    with db.lock, db.connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        return cur.rowcount > 0
