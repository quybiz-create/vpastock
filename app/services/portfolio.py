"""
Portfolio Tracker - Phase 12

Quản lý danh mục đầu tư:
- Lệnh OPEN: đang nắm, P/L tính realtime từ giá hiện tại
- Lệnh CLOSED: đã chốt, P/L realized lưu cố định

SCHEMA:
  portfolio (
    id INTEGER PRIMARY KEY,
    symbol TEXT,
    quantity INTEGER,
    entry_price REAL,
    entry_date TEXT,           -- YYYY-MM-DD
    status TEXT DEFAULT 'open', -- 'open' / 'closed'
    exit_price REAL,           -- null nếu open
    exit_date TEXT,            -- YYYY-MM-DD, null nếu open
    note TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
  )

Endpoints (in api_portfolio.py):
- GET  /portfolio              → list all (kèm P/L realtime cho open)
- POST /portfolio              → thêm lệnh mới
- POST /portfolio/{id}/close   → đóng lệnh (set exit price + date)
- DELETE /portfolio/{id}       → xóa hẳn
- PATCH /portfolio/{id}        → update note/quantity
- GET  /portfolio/summary      → dashboard tổng
"""
from __future__ import annotations
import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger


_DB_PATH = Path(__file__).parent.parent.parent / "data" / "portfolio.db"
_DB_PATH.parent.mkdir(exist_ok=True, parents=True)


def _get_db():
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_portfolio_db():
    """Init bảng portfolio."""
    conn = _get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                entry_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                exit_price REAL,
                exit_date TEXT,
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_portfolio_status ON portfolio(status);
            CREATE INDEX IF NOT EXISTS idx_portfolio_symbol ON portfolio(symbol);
        """)
        conn.commit()
        logger.info(f"[portfolio] DB initialized at {_DB_PATH}")
    finally:
        conn.close()


# ============================================================
# Price cache - tránh fetch lặp khi gọi summary
# ============================================================
import time
_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
_PRICE_TTL = 60  # 60 giây


async def _get_current_price(symbol: str) -> Optional[float]:
    """Lấy giá đóng cửa gần nhất. Cache 60s."""
    symbol = symbol.upper().strip()
    now = time.time()
    cached = _PRICE_CACHE.get(symbol)
    if cached and (now - cached["at"]) < _PRICE_TTL:
        return cached["price"]
    
    try:
        from app.data.vnstock_client import vnstock_client
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        df = await asyncio.wait_for(
            vnstock_client.get_history(symbol, start=start, end=end),
            timeout=6.0,
        )
        if df is None or df.empty:
            return None
        price = float(df.iloc[-1]["close"])
        _PRICE_CACHE[symbol] = {"price": price, "at": now}
        return price
    except Exception as e:
        logger.debug(f"[portfolio] price {symbol} fail: {e}")
        return None


# ============================================================
# CRUD
# ============================================================
def add_position(
    symbol: str,
    quantity: int,
    entry_price: float,
    entry_date: str,
    note: str = "",
) -> Dict[str, Any]:
    """Thêm lệnh mới (status='open')."""
    symbol = symbol.upper().strip()
    if quantity <= 0:
        raise ValueError("Số lượng phải > 0")
    if entry_price <= 0:
        raise ValueError("Giá entry phải > 0")
    
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        cur = conn.execute(
            """INSERT INTO portfolio
               (symbol, quantity, entry_price, entry_date, status, note, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'open', ?, ?, ?)""",
            (symbol, quantity, entry_price, entry_date, note, now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM portfolio WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def close_position(
    position_id: int,
    exit_price: float,
    exit_date: str,
) -> Optional[Dict[str, Any]]:
    """Đóng lệnh (status='closed')."""
    if exit_price <= 0:
        raise ValueError("Giá đóng phải > 0")
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM portfolio WHERE id = ?", (position_id,)).fetchone()
        if not row:
            return None
        if row["status"] == "closed":
            raise ValueError("Lệnh đã đóng từ trước")
        
        conn.execute(
            """UPDATE portfolio SET status = 'closed', exit_price = ?, exit_date = ?, updated_at = ?
               WHERE id = ?""",
            (exit_price, exit_date, now, position_id),
        )
        conn.commit()
        new_row = conn.execute("SELECT * FROM portfolio WHERE id = ?", (position_id,)).fetchone()
        return dict(new_row)
    finally:
        conn.close()


def delete_position(position_id: int) -> bool:
    conn = _get_db()
    try:
        cur = conn.execute("DELETE FROM portfolio WHERE id = ?", (position_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_note(position_id: int, note: str) -> Optional[Dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        cur = conn.execute(
            "UPDATE portfolio SET note = ?, updated_at = ? WHERE id = ?",
            (note, now, position_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM portfolio WHERE id = ?", (position_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def list_positions(status: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = _get_db()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM portfolio WHERE status = ? ORDER BY entry_date DESC, id DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM portfolio ORDER BY status ASC, entry_date DESC, id DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ============================================================
# P/L calculation + summary
# ============================================================
async def enrich_with_pl(positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Thêm field current_price + unrealized_pl + pct cho mỗi position.
    
    Open: fetch giá hiện tại
    Closed: dùng exit_price làm "current"
    """
    # Gom danh sách symbol cần fetch (chỉ open)
    open_symbols = list({p["symbol"] for p in positions if p["status"] == "open"})
    
    # Fetch song song
    if open_symbols:
        prices = await asyncio.gather(
            *[_get_current_price(s) for s in open_symbols],
            return_exceptions=True,
        )
        price_map = {}
        for sym, p in zip(open_symbols, prices):
            if isinstance(p, Exception) or p is None:
                price_map[sym] = None
            else:
                price_map[sym] = p
    else:
        price_map = {}
    
    enriched = []
    for p in positions:
        out = dict(p)
        entry = float(p["entry_price"])
        qty = int(p["quantity"])
        
        if p["status"] == "open":
            cur_price = price_map.get(p["symbol"])
            out["current_price"] = cur_price
            if cur_price is not None:
                pl = (cur_price - entry) * qty
                pl_pct = (cur_price - entry) / entry * 100 if entry > 0 else 0
                out["pl"] = round(pl, 2)
                out["pl_pct"] = round(pl_pct, 2)
                out["pl_realized"] = False
            else:
                out["pl"] = None
                out["pl_pct"] = None
                out["pl_realized"] = False
        else:  # closed
            exit_p = float(p.get("exit_price") or 0)
            out["current_price"] = exit_p
            if exit_p > 0:
                pl = (exit_p - entry) * qty
                pl_pct = (exit_p - entry) / entry * 100 if entry > 0 else 0
                out["pl"] = round(pl, 2)
                out["pl_pct"] = round(pl_pct, 2)
                out["pl_realized"] = True
            else:
                out["pl"] = 0
                out["pl_pct"] = 0
                out["pl_realized"] = True
        
        # Tổng giá trị position
        out["entry_value"] = round(entry * qty, 2)
        if out.get("current_price"):
            out["current_value"] = round(out["current_price"] * qty, 2)
        else:
            out["current_value"] = None
        
        enriched.append(out)
    return enriched


async def get_summary() -> Dict[str, Any]:
    """Dashboard summary: tổng vốn, tổng P/L, top winners/losers."""
    all_pos = list_positions()
    enriched = await enrich_with_pl(all_pos)
    
    open_pos = [p for p in enriched if p["status"] == "open"]
    closed_pos = [p for p in enriched if p["status"] == "closed"]
    
    # Tổng vốn đang đầu tư (open)
    total_entry_value_open = sum(p["entry_value"] for p in open_pos)
    total_current_value_open = sum(p["current_value"] or 0 for p in open_pos if p.get("current_value") is not None)
    total_unrealized_pl = sum(p.get("pl") or 0 for p in open_pos if p.get("pl") is not None)
    
    # P/L đã realized từ closed
    total_realized_pl = sum(p.get("pl") or 0 for p in closed_pos)
    
    # Win rate trên closed
    closed_wins = [p for p in closed_pos if (p.get("pl") or 0) > 0]
    closed_losses = [p for p in closed_pos if (p.get("pl") or 0) < 0]
    win_rate = (len(closed_wins) / len(closed_pos) * 100) if closed_pos else 0
    
    # Top winners / losers (cả open + closed)
    pos_with_pl = [p for p in enriched if p.get("pl_pct") is not None]
    top_winners = sorted(pos_with_pl, key=lambda x: x["pl_pct"], reverse=True)[:3]
    top_losers = sorted(pos_with_pl, key=lambda x: x["pl_pct"])[:3]
    
    return {
        "total_positions": len(all_pos),
        "open_count": len(open_pos),
        "closed_count": len(closed_pos),
        "total_entry_value_open": round(total_entry_value_open, 2),
        "total_current_value_open": round(total_current_value_open, 2),
        "total_unrealized_pl": round(total_unrealized_pl, 2),
        "total_unrealized_pl_pct": round(
            (total_unrealized_pl / total_entry_value_open * 100) if total_entry_value_open > 0 else 0,
            2,
        ),
        "total_realized_pl": round(total_realized_pl, 2),
        "win_rate": round(win_rate, 1),
        "winners_count": len(closed_wins),
        "losers_count": len(closed_losses),
        "top_winners": [
            {"id": p["id"], "symbol": p["symbol"], "pl": p["pl"], "pl_pct": p["pl_pct"], "status": p["status"]}
            for p in top_winners
        ],
        "top_losers": [
            {"id": p["id"], "symbol": p["symbol"], "pl": p["pl"], "pl_pct": p["pl_pct"], "status": p["status"]}
            for p in top_losers
        ],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
