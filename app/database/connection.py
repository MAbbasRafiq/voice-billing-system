"""SQLite connection helpers."""

import sqlite3
from pathlib import Path

from app.database.models import ALL_TABLES

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "database.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        for ddl in ALL_TABLES:
            conn.execute(ddl)
        conn.commit()
    finally:
        conn.close()
