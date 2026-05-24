"""
REST API endpoints cho Watchlist & Alert.
"""
from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

from app.db.database import get_db, dict_from_row


router = APIRouter()


# ============================================================
# PYDANTIC SCHEMAS
# ============================================================
class WatchlistCreate(BaseModel):
    user_fp: str = Field(..., min_length=8, description="Browser fingerprint")
    name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = None
    is_default: bool = False


class ItemAdd(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)
    note: Optional[str] = None
    added_price: Optional[float] = None


class AlertCreate(BaseModel):
    user_fp: str = Field(..., min_length=8)
    symbol: str = Field(..., min_length=1, max_length=10)
    alert_type: str = Field(..., pattern="^(price_above|price_below|pct_change)$")
    threshold: float = Field(..., gt=0)
    note: Optional[str] = None


# ============================================================
# WATCHLIST CRUD
# ============================================================
@router.get("/list")
async def list_watchlists(user_fp: str = Query(..., min_length=8)):
    """Liet ke tat ca watchlists cua user, kem so luong items."""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT w.*, COUNT(wi.id) as item_count
            FROM watchlists w
            LEFT JOIN watchlist_items wi ON wi.watchlist_id = w.id
            WHERE w.user_fp = ?
            GROUP BY w.id
            ORDER BY w.is_default DESC, w.created_at ASC
        """, (user_fp,))
        return {"watchlists": [dict_from_row(row) for row in cursor.fetchall()]}


@router.post("/create")
async def create_watchlist(payload: WatchlistCreate):
    """Tao watchlist moi."""
    with get_db() as conn:
        # If is_default=True, unset others
        if payload.is_default:
            conn.execute(
                "UPDATE watchlists SET is_default = 0 WHERE user_fp = ?",
                (payload.user_fp,),
            )
        cursor = conn.execute("""
            INSERT INTO watchlists (user_fp, name, description, is_default)
            VALUES (?, ?, ?, ?)
        """, (payload.user_fp, payload.name, payload.description, int(payload.is_default)))
        wl_id = cursor.lastrowid
        return {"id": wl_id, "message": "Watchlist created"}


@router.delete("/{wl_id}")
async def delete_watchlist(wl_id: int, user_fp: str = Query(..., min_length=8)):
    """Xoa watchlist (cascade items)."""
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM watchlists WHERE id = ? AND user_fp = ?",
            (wl_id, user_fp),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Watchlist not found")
        return {"message": "Watchlist deleted"}


# ============================================================
# WATCHLIST ITEMS
# ============================================================
@router.get("/{wl_id}/items")
async def get_items(wl_id: int, user_fp: str = Query(..., min_length=8)):
    """Lay danh sach ma trong watchlist."""
    with get_db() as conn:
        # Verify ownership
        owner = conn.execute(
            "SELECT user_fp FROM watchlists WHERE id = ?", (wl_id,)
        ).fetchone()
        if not owner or owner["user_fp"] != user_fp:
            raise HTTPException(404, "Watchlist not found")
        
        cursor = conn.execute("""
            SELECT * FROM watchlist_items
            WHERE watchlist_id = ?
            ORDER BY added_at DESC
        """, (wl_id,))
        return {"items": [dict_from_row(row) for row in cursor.fetchall()]}


@router.post("/{wl_id}/add")
async def add_item(wl_id: int, payload: ItemAdd, user_fp: str = Query(..., min_length=8)):
    """Them ma vao watchlist."""
    symbol = payload.symbol.upper()
    with get_db() as conn:
        # Verify ownership
        owner = conn.execute(
            "SELECT user_fp FROM watchlists WHERE id = ?", (wl_id,)
        ).fetchone()
        if not owner or owner["user_fp"] != user_fp:
            raise HTTPException(404, "Watchlist not found")
        
        try:
            cursor = conn.execute("""
                INSERT INTO watchlist_items (watchlist_id, symbol, note, added_price)
                VALUES (?, ?, ?, ?)
            """, (wl_id, symbol, payload.note, payload.added_price))
            return {"id": cursor.lastrowid, "symbol": symbol, "message": "Added"}
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                raise HTTPException(409, f"Symbol {symbol} already in watchlist")
            raise HTTPException(500, str(e))


@router.delete("/{wl_id}/remove/{symbol}")
async def remove_item(wl_id: int, symbol: str, user_fp: str = Query(..., min_length=8)):
    """Xoa ma khoi watchlist."""
    symbol = symbol.upper()
    with get_db() as conn:
        # Verify ownership
        owner = conn.execute(
            "SELECT user_fp FROM watchlists WHERE id = ?", (wl_id,)
        ).fetchone()
        if not owner or owner["user_fp"] != user_fp:
            raise HTTPException(404, "Watchlist not found")
        
        cursor = conn.execute(
            "DELETE FROM watchlist_items WHERE watchlist_id = ? AND symbol = ?",
            (wl_id, symbol),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, f"Symbol {symbol} not found")
        return {"message": f"Removed {symbol}"}


# ============================================================
# ALERTS
# ============================================================
@router.post("/alert/create")
async def create_alert(payload: AlertCreate):
    """Tao alert gia."""
    symbol = payload.symbol.upper()
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO alerts (user_fp, symbol, alert_type, threshold, note, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (payload.user_fp, symbol, payload.alert_type, payload.threshold, payload.note))
        return {"id": cursor.lastrowid, "message": "Alert created"}


@router.get("/alert/list")
async def list_alerts(
    user_fp: str = Query(..., min_length=8),
    active_only: bool = Query(True),
):
    """Liet ke alerts."""
    with get_db() as conn:
        sql = "SELECT * FROM alerts WHERE user_fp = ?"
        params = [user_fp]
        if active_only:
            sql += " AND is_active = 1"
        sql += " ORDER BY created_at DESC"
        cursor = conn.execute(sql, params)
        return {"alerts": [dict_from_row(row) for row in cursor.fetchall()]}


@router.delete("/alert/{alert_id}")
async def delete_alert(alert_id: int, user_fp: str = Query(..., min_length=8)):
    """Xoa alert."""
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM alerts WHERE id = ? AND user_fp = ?",
            (alert_id, user_fp),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Alert not found")
        return {"message": "Alert deleted"}

# ============================================================
# ALERT NOTIFICATION (Phase 3 Day 3)
# ============================================================
@router.get("/alert/triggered")
async def get_triggered_alerts(
    user_fp: str = Query(..., min_length=8),
    since: Optional[str] = Query(None, description="ISO datetime - chi tra ve alerts trigger sau thoi diem nay"),
):
    """
    Lay alerts da trigger (triggered_at IS NOT NULL).
    Frontend goi moi 30s, neu co alert moi -> show notification.
    """
    with get_db() as conn:
        sql = """
            SELECT * FROM alerts 
            WHERE user_fp = ? AND triggered_at IS NOT NULL AND is_active = 1
        """
        params = [user_fp]
        
        if since:
            sql += " AND triggered_at > ?"
            params.append(since)
        
        sql += " ORDER BY triggered_at DESC LIMIT 20"
        
        cursor = conn.execute(sql, params)
        return {"alerts": [dict_from_row(row) for row in cursor.fetchall()]}


@router.post("/alert/{alert_id}/ack")
async def ack_alert(alert_id: int, user_fp: str = Query(..., min_length=8)):
    """
    User da thay notification -> set is_active=0 de khong notify nua.
    """
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE alerts SET is_active = 0 WHERE id = ? AND user_fp = ?",
            (alert_id, user_fp),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Alert not found")
        return {"message": "Alert acknowledged"}