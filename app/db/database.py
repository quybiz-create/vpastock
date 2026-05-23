"""
SQLite database setup cho vpastock.
Single file vpastock.db luu trong root project.
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Iterator


# Database file path: <project_root>/vpastock.db
DB_PATH = Path(__file__).parent.parent.parent / "vpastock.db"


# ============================================================
# SCHEMA
# ============================================================
SCHEMA_SQL = """
-- 1. Watchlists
CREATE TABLE IF NOT EXISTS watchlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_fp TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    is_default INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wl_user_fp ON watchlists(user_fp);

-- 2. Watchlist items
CREATE TABLE IF NOT EXISTS watchlist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watchlist_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    note TEXT,
    added_price REAL,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (watchlist_id) REFERENCES watchlists(id) ON DELETE CASCADE,
    UNIQUE(watchlist_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_wi_wl ON watchlist_items(watchlist_id);
CREATE INDEX IF NOT EXISTS idx_wi_symbol ON watchlist_items(symbol);

-- 3. Alerts
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_fp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    threshold REAL NOT NULL,
    note TEXT,
    is_active INTEGER DEFAULT 1,
    triggered_at DATETIME,
    last_checked DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alert_user_fp ON alerts(user_fp);
CREATE INDEX IF NOT EXISTS idx_alert_active ON alerts(is_active);
"""


# ============================================================
# CONNECTION & INIT
# ============================================================
def init_db():
    """Khoi tao database (chay 1 lan luc startup)."""
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    print(f"[DB] Initialized at {DB_PATH}")


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """
    Context manager tra ve SQLite connection.
    Tu dong commit + close.
    
    Usage:
        with get_db() as conn:
            cursor = conn.execute("SELECT * FROM watchlists")
            rows = cursor.fetchall()
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Tra ve dict-like rows
    conn.execute("PRAGMA foreign_keys = ON")  # Bat foreign key constraints
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def dict_from_row(row) -> dict:
    """Chuyen sqlite3.Row sang dict thuong."""
    return dict(row) if row else {}


# ============================================================
# RUN STANDALONE: python -m app.db.database
# ============================================================
if __name__ == "__main__":
    init_db()
    with get_db() as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row["name"] for row in cursor.fetchall()]
        print(f"[DB] Tables: {tables}")