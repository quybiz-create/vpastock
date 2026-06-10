"""
Breadth History - Phase 14D
Lưu daily snapshot của market breadth metrics để vẽ chart lịch sử.
"""
from __future__ import annotations
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List
from loguru import logger


DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "breadth_history.db"


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS breadth_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL UNIQUE,
                score REAL NOT NULL,
                label TEXT,
                total INTEGER,
                advance INTEGER,
                decline INTEGER,
                unchanged INTEGER,
                ad_ratio INTEGER,
                ad_pct REAL,
                pct_above_ma20 REAL,
                pct_above_ma50 REAL,
                ad_pct_5d REAL,
                ma20_trend_pct REAL,
                raw_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshot_date ON breadth_snapshots(snapshot_date)")
        conn.commit()
        logger.info(f"[breadth_history] DB ready at {DB_PATH}")
    finally:
        conn.close()


def save_snapshot(result: Dict[str, Any]) -> bool:
    """Lưu snapshot vào DB. 1 ngày 1 record (replace nếu chạy lại trong ngày)."""
    try:
        breadth = result.get("breadth", {})
        if not breadth:
            return False
        
        today = datetime.now().strftime("%Y-%m-%d")
        
        conn = sqlite3.connect(str(DB_PATH))
        try:
            conn.execute("""
                INSERT INTO breadth_snapshots
                  (snapshot_date, score, label, total, advance, decline, unchanged,
                   ad_ratio, ad_pct, pct_above_ma20, pct_above_ma50,
                   ad_pct_5d, ma20_trend_pct, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_date) DO UPDATE SET
                    score=excluded.score,
                    label=excluded.label,
                    total=excluded.total,
                    advance=excluded.advance,
                    decline=excluded.decline,
                    unchanged=excluded.unchanged,
                    ad_ratio=excluded.ad_ratio,
                    ad_pct=excluded.ad_pct,
                    pct_above_ma20=excluded.pct_above_ma20,
                    pct_above_ma50=excluded.pct_above_ma50,
                    ad_pct_5d=excluded.ad_pct_5d,
                    ma20_trend_pct=excluded.ma20_trend_pct,
                    raw_json=excluded.raw_json
            """, (
                today,
                result.get("score", 0),
                result.get("label", ""),
                breadth.get("total", 0),
                breadth.get("advance", 0),
                breadth.get("decline", 0),
                breadth.get("unchanged", 0),
                breadth.get("ad_ratio", 0),
                breadth.get("ad_pct", 0.0),
                breadth.get("pct_above_ma20", 0.0),
                breadth.get("pct_above_ma50", 0.0),
                breadth.get("ad_pct_5d", 0.0),
                breadth.get("ma20_trend_pct", 0.0),
                json.dumps(breadth, ensure_ascii=False, default=str),
            ))
            conn.commit()
            logger.info(f"[breadth_history] saved snapshot score={result.get('score')}")
            return True
        finally:
            conn.close()
    except Exception as e:
        logger.exception(f"[breadth_history] save fail: {e}")
        return False


def get_history(days: int = 30) -> List[Dict[str, Any]]:
    """Lấy lịch sử N ngày gần nhất."""
    try:
        if not DB_PATH.exists():
            return []
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            cursor = conn.execute("""
                SELECT snapshot_date, score, label, total, advance, decline, unchanged,
                       ad_ratio, ad_pct, pct_above_ma20, pct_above_ma50,
                       ad_pct_5d, ma20_trend_pct
                FROM breadth_snapshots
                WHERE snapshot_date >= ?
                ORDER BY snapshot_date ASC
            """, (cutoff,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        logger.exception(f"[breadth_history] get_history fail: {e}")
        return []


# Auto-init when imported
init_db()
