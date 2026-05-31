"""
Fear & Greed History - SQLite storage.

Lưu snapshot mỗi lần compute_fear_greed() được gọi (cache 30 phút sẽ
giới hạn tần suất ghi tự nhiên xuống ~30 phút/lần khi có user gọi API).

Schema:
    fg_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,   -- ISO 8601 UTC
        score REAL NOT NULL,        -- 0..100
        label TEXT,
        vnindex_value REAL,
        vnindex_ma200 REAL,
        rsi REAL,
        pct_above_ma REAL,
        vol_ratio REAL,
        atr_ratio REAL,
        momentum_5d REAL
    )
"""
from __future__ import annotations
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from loguru import logger


# Database path: /opt/vpastock/data/fg_history.db (production) hoặc local
_DEFAULT_DB_DIR = os.environ.get(
    "VPASTOCK_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
)
_DB_PATH = os.path.abspath(os.path.join(_DEFAULT_DB_DIR, "fg_history.db"))

# Minimum gap between snapshots to avoid spamming (seconds).
# Cache TTL của fear-greed endpoint = 30 phút, nhưng có thể có nhiều
# instance gọi đồng thời → debounce thêm 25 phút để an toàn.
_MIN_SNAPSHOT_GAP_SEC = 25 * 60


def _ensure_dir():
    d = os.path.dirname(_DB_PATH)
    if not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


@contextmanager
def _conn():
    _ensure_dir()
    c = sqlite3.connect(_DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    """Create table if not exists. Safe to call repeatedly."""
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS fg_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                score REAL NOT NULL,
                label TEXT,
                vnindex_value REAL,
                vnindex_ma200 REAL,
                rsi REAL,
                pct_above_ma REAL,
                vol_ratio REAL,
                atr_ratio REAL,
                momentum_5d REAL
            )
            """
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_fg_timestamp ON fg_history(timestamp)"
        )
    logger.info(f"[fg_history] DB ready at {_DB_PATH}")


def _last_snapshot_ts() -> Optional[datetime]:
    """Get timestamp of latest snapshot, or None if empty."""
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT timestamp FROM fg_history ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            return datetime.fromisoformat(row["timestamp"])
    except Exception as e:
        logger.warning(f"[fg_history] last_snapshot_ts fail: {e}")
        return None


def save_snapshot(fg_data: Dict[str, Any]) -> bool:
    """
    Save F&G result into DB. Returns True if saved, False if skipped
    (e.g. dedupe within _MIN_SNAPSHOT_GAP_SEC or invalid data).

    Accepts the exact dict returned by compute_fear_greed().
    """
    try:
        # Skip if data is invalid
        score = fg_data.get("score")
        if score is None or fg_data.get("error"):
            return False

        # Dedupe: only save if last snapshot is older than threshold
        last = _last_snapshot_ts()
        if last:
            gap = (datetime.utcnow() - last).total_seconds()
            # Allow if we can't parse (assume different) OR gap big enough
            if gap < _MIN_SNAPSHOT_GAP_SEC:
                logger.debug(f"[fg_history] skip (only {gap:.0f}s since last)")
                return False

        comps = fg_data.get("components") or {}
        vnindex = fg_data.get("vnindex") or {}

        with _conn() as c:
            c.execute(
                """
                INSERT INTO fg_history (
                    timestamp, score, label,
                    vnindex_value, vnindex_ma200,
                    rsi, pct_above_ma, vol_ratio, atr_ratio, momentum_5d
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    datetime.utcnow().isoformat(),
                    float(score),
                    fg_data.get("label"),
                    vnindex.get("value"),
                    vnindex.get("ma200"),
                    (comps.get("rsi") or {}).get("value"),
                    (comps.get("ma200") or {}).get("value"),
                    (comps.get("volume") or {}).get("value"),
                    (comps.get("volatility") or {}).get("value"),
                    (comps.get("momentum") or {}).get("value"),
                ),
            )
        logger.info(f"[fg_history] saved snapshot score={score}")
        return True
    except Exception as e:
        logger.exception(f"[fg_history] save fail: {e}")
        return False


def get_history(days: int = 30) -> List[Dict[str, Any]]:
    """Return list of snapshots in the last `days` days, oldest-first."""
    try:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with _conn() as c:
            rows = c.execute(
                """
                SELECT timestamp, score, label, vnindex_value, rsi,
                       pct_above_ma, vol_ratio, atr_ratio, momentum_5d
                FROM fg_history
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
                """,
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.exception(f"[fg_history] get_history fail: {e}")
        return []


def get_stats() -> Dict[str, Any]:
    """Return summary stats: total count, oldest, newest, avg score."""
    try:
        with _conn() as c:
            row = c.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    MIN(timestamp) AS oldest,
                    MAX(timestamp) AS newest,
                    AVG(score) AS avg_score,
                    MIN(score) AS min_score,
                    MAX(score) AS max_score
                FROM fg_history
                """
            ).fetchone()
            return dict(row) if row else {}
    except Exception as e:
        logger.exception(f"[fg_history] get_stats fail: {e}")
        return {}


# Ensure DB is ready when module is imported (idempotent + cheap)
try:
    init_db()
except Exception as _e:
    logger.warning(f"[fg_history] init_db at import fail: {_e}")


if __name__ == "__main__":
    # Quick self-test
    import json
    init_db()
    sample = {
        "score": 53.2,
        "label": "Trung tính",
        "vnindex": {"value": 1858.1, "ma200": 1738.6},
        "components": {
            "rsi": {"value": 47.4},
            "ma200": {"value": 6.87},
            "volume": {"value": 0.35},
            "volatility": {"value": 0.44},
            "momentum": {"value": -1.01},
        },
    }
    print("Save:", save_snapshot(sample))
    print("Stats:", json.dumps(get_stats(), indent=2))
    print("History (last 30d):", len(get_history(30)), "rows")
