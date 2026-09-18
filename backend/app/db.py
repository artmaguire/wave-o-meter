"""Shared SQLite connection helper.

Both the forecast cache and the session log use the same SQLite file; this
centralises connection setup (WAL mode, row factory, dir creation) and the
write lock so the two modules don't duplicate it.
"""

from __future__ import annotations

import sqlite3
import threading

from . import config

# Single process-wide lock guarding writes to the shared SQLite file.
lock = threading.Lock()


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
