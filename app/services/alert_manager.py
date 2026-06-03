"""
Smart Alerts - Phase 11

Hệ thống alert tự động theo dõi các sự kiện Wyckoff trên các mã user chọn.
Chạy nền mỗi 15 phút, push qua Telegram khi có sự kiện.

SCHEMA:
  alerts (
    id INTEGER PRIMARY KEY,
    symbol TEXT,
    alert_type TEXT,        -- 'phase_change', 'spring', 'utad', 'phase_d', 'breakout', 'sos_sow', 'any'
    enabled INTEGER DEFAULT 1,
    note TEXT,              -- ghi chú user (vd "mua khi sang Phase D")
    last_state TEXT,        -- JSON snapshot của Wyckoff lần check cuối
    last_checked_at TEXT,   -- ISO timestamp
    last_triggered_at TEXT,
    trigger_count INTEGER DEFAULT 0,
    created_at TEXT
  )
  
  alert_history (
    id INTEGER PRIMARY KEY,
    alert_id INTEGER,
    symbol TEXT,
    event_type TEXT,
    event_desc TEXT,
    old_state TEXT,        -- JSON
    new_state TEXT,        -- JSON
    triggered_at TEXT
  )

ALERT TYPES:
- phase_change: bất kỳ thay đổi setup/phase
- spring: phát hiện Spring (Phase C accumulation)
- utad: phát hiện UTAD (Phase C distribution)
- phase_d: chuyển sang Phase D (entry zone)
- breakout: phá TR↑ hoặc TR↓
- sos_sow: SOS hoặc SOW xuất hiện
- any: tất cả
"""
from __future__ import annotations
import asyncio
import json
import os
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger
import httpx


# ============================================================
# DB setup
# ============================================================
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "alerts.db"
_DB_PATH.parent.mkdir(exist_ok=True, parents=True)


def _get_db():
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Khởi tạo bảng nếu chưa có."""
    conn = _get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                note TEXT DEFAULT '',
                last_state TEXT DEFAULT '',
                last_checked_at TEXT DEFAULT '',
                last_triggered_at TEXT DEFAULT '',
                trigger_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_alerts_enabled ON alerts(enabled);
            CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol);
            
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_desc TEXT NOT NULL,
                old_state TEXT DEFAULT '',
                new_state TEXT DEFAULT '',
                triggered_at TEXT NOT NULL,
                FOREIGN KEY(alert_id) REFERENCES alerts(id)
            );
            
            CREATE INDEX IF NOT EXISTS idx_history_alert ON alert_history(alert_id);
            CREATE INDEX IF NOT EXISTS idx_history_time ON alert_history(triggered_at);
        """)
        conn.commit()
        logger.info(f"[alerts] DB initialized at {_DB_PATH}")
    finally:
        conn.close()


# ============================================================
# CRUD
# ============================================================
def create_alert(symbol: str, alert_type: str, note: str = "") -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    valid_types = {"phase_change", "spring", "utad", "phase_d", "breakout", "sos_sow", "any"}
    if alert_type not in valid_types:
        raise ValueError(f"alert_type must be one of {valid_types}")
    
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        cur = conn.execute(
            "INSERT INTO alerts (symbol, alert_type, enabled, note, created_at) VALUES (?, ?, 1, ?, ?)",
            (symbol, alert_type, note, now),
        )
        conn.commit()
        return _row_to_dict(conn.execute("SELECT * FROM alerts WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        conn.close()


def list_alerts(enabled_only: bool = False) -> List[Dict[str, Any]]:
    conn = _get_db()
    try:
        sql = "SELECT * FROM alerts"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY created_at DESC"
        return [_row_to_dict(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def get_alert(alert_id: int) -> Optional[Dict[str, Any]]:
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def delete_alert(alert_id: int) -> bool:
    conn = _get_db()
    try:
        cur = conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        conn.execute("DELETE FROM alert_history WHERE alert_id = ?", (alert_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def toggle_alert(alert_id: int) -> Optional[Dict[str, Any]]:
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if not row:
            return None
        new_enabled = 0 if row["enabled"] else 1
        conn.execute("UPDATE alerts SET enabled = ? WHERE id = ?", (new_enabled, alert_id))
        conn.commit()
        return _row_to_dict(conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone())
    finally:
        conn.close()


def get_alert_history(alert_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM alert_history WHERE alert_id = ? ORDER BY triggered_at DESC LIMIT ?",
            (alert_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recent_history(limit: int = 30) -> List[Dict[str, Any]]:
    """Lấy history tổng (cho dashboard)."""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM alert_history ORDER BY triggered_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _row_to_dict(row) -> Dict[str, Any]:
    if not row:
        return {}
    d = dict(row)
    # Parse last_state JSON
    if d.get("last_state"):
        try:
            d["last_state_parsed"] = json.loads(d["last_state"])
        except Exception:
            d["last_state_parsed"] = None
    return d


# ============================================================
# Alert checking logic
# ============================================================
def _extract_state(wyckoff_result: Dict[str, Any]) -> Dict[str, Any]:
    """Trích state quan trọng từ Wyckoff result để so sánh."""
    tr = wyckoff_result.get("trading_range") or {}
    events = wyckoff_result.get("events", [])
    return {
        "setup": wyckoff_result.get("setup"),
        "phase": wyckoff_result.get("phase"),
        "confidence": wyckoff_result.get("confidence"),
        "tr_high": tr.get("high"),
        "tr_low": tr.get("low"),
        "event_types": sorted(set(e["type"] for e in events)),
        "events_count": len(events),
    }


def _detect_changes(
    alert_type: str,
    old_state: Optional[Dict[str, Any]],
    new_state: Dict[str, Any],
    current_price: Optional[float] = None,
) -> List[Dict[str, str]]:
    """So sánh old vs new state, return list of triggered events.
    
    Returns: [{event_type, event_desc, emoji}]
    """
    triggered = []
    
    if old_state is None:
        # Lần check đầu tiên - không trigger, chỉ lưu state
        return triggered
    
    old_setup = old_state.get("setup")
    new_setup = new_state.get("setup")
    old_phase = old_state.get("phase")
    new_phase = new_state.get("phase")
    old_events = set(old_state.get("event_types", []))
    new_events = set(new_state.get("event_types", []))
    fresh_events = new_events - old_events
    
    # 1. Setup/Phase change
    if alert_type in ("phase_change", "any"):
        if old_setup != new_setup or old_phase != new_phase:
            setup_vi = {"accumulation": "Tích lũy", "distribution": "Phân phối", "none": "N/A"}
            old_s = setup_vi.get(old_setup, old_setup)
            new_s = setup_vi.get(new_setup, new_setup)
            triggered.append({
                "event_type": "phase_change",
                "event_desc": f"Wyckoff chuyển: {old_s} Phase {old_phase} → {new_s} Phase {new_phase}",
                "emoji": "🔄",
            })
    
    # 2. Phase D (entry zone) - quan trọng nhất
    if alert_type in ("phase_d", "any"):
        if old_phase != "D" and new_phase == "D":
            setup_vi = "Tích lũy" if new_setup == "accumulation" else "Phân phối"
            triggered.append({
                "event_type": "phase_d",
                "event_desc": f"🎯 ENTRY ZONE - {setup_vi} Phase D (giai đoạn vàng để vào lệnh)",
                "emoji": "🎯",
            })
    
    # 3. Spring xuất hiện
    if alert_type in ("spring", "any"):
        if "Spring" in fresh_events:
            triggered.append({
                "event_type": "spring",
                "event_desc": "Spring xuất hiện - đáy giả + đảo chiều (cơ hội mua)",
                "emoji": "🟢",
            })
    
    # 4. UTAD xuất hiện
    if alert_type in ("utad", "any"):
        if "UTAD" in fresh_events:
            triggered.append({
                "event_type": "utad",
                "event_desc": "UTAD xuất hiện - đỉnh giả + đảo chiều (cảnh báo bán)",
                "emoji": "🔴",
            })
    
    # 5. SOS / SOW
    if alert_type in ("sos_sow", "any"):
        if "SOS" in fresh_events:
            triggered.append({
                "event_type": "sos",
                "event_desc": "SOS - Sign of Strength (xu hướng tăng xác nhận)",
                "emoji": "📈",
            })
        if "SOW" in fresh_events:
            triggered.append({
                "event_type": "sow",
                "event_desc": "SOW - Sign of Weakness (xu hướng giảm xác nhận)",
                "emoji": "📉",
            })
    
    # 6. Breakout TR
    if alert_type in ("breakout", "any") and current_price is not None:
        new_tr_high = new_state.get("tr_high")
        new_tr_low = new_state.get("tr_low")
        old_tr_high = old_state.get("tr_high")
        old_tr_low = old_state.get("tr_low")
        # Check nếu giá vừa phá TR
        if new_tr_high and current_price > new_tr_high * 1.005:
            triggered.append({
                "event_type": "breakout_up",
                "event_desc": f"Giá phá TR↑ ({new_tr_high}) — breakout tăng",
                "emoji": "🚀",
            })
        elif new_tr_low and current_price < new_tr_low * 0.995:
            triggered.append({
                "event_type": "breakdown",
                "event_desc": f"Giá phá TR↓ ({new_tr_low}) — breakdown giảm",
                "emoji": "💥",
            })
    
    return triggered


async def _send_telegram_alert(symbol: str, events: List[Dict], current_price: Optional[float]):
    """Gửi alert qua Telegram bot."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.warning("[alerts] Telegram not configured")
        return False
    
    app_url = os.environ.get("APP_URL", "https://app.vpastock.com")
    
    lines = [f"🔔 <b>ALERT: {symbol}</b>"]
    for e in events:
        lines.append(f"{e['emoji']} {e['event_desc']}")
    if current_price is not None:
        lines.append(f"💰 Giá hiện tại: <b>{current_price}</b>")
    lines.append(f"\n🔗 <a href='{app_url}/stock-detail-live.html?sym={symbol}'>Xem chi tiết</a>")
    text = "\n".join(lines)
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            )
            r.raise_for_status()
        logger.info(f"[alerts] Telegram sent for {symbol}: {len(events)} events")
        return True
    except Exception as e:
        logger.error(f"[alerts] Telegram fail: {e}")
        return False


async def check_one_alert(alert: Dict[str, Any]) -> int:
    """Check 1 alert, trả về số events trigger (0 nếu không có)."""
    symbol = alert["symbol"]
    alert_id = alert["id"]
    alert_type = alert["alert_type"]
    
    try:
        # Load Wyckoff analysis
        from app.services.wyckoff import analyze_wyckoff
        from app.data.vnstock_client import vnstock_client
        
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
        df = await asyncio.wait_for(
            vnstock_client.get_history(symbol, start=start, end=end),
            timeout=10.0,
        )
        if df is None or df.empty or len(df) < 50:
            logger.debug(f"[alerts] {symbol} no data")
            return 0
        
        df = df[~df.index.duplicated(keep="last")].sort_index()
        bars = []
        for idx, row in df.iterrows():
            try:
                t = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
            except Exception:
                t = str(idx)
            bars.append({
                "time": t,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0) or 0),
            })
        
        result = analyze_wyckoff(bars, period=200)
        new_state = _extract_state(result)
        current_price = bars[-1]["close"] if bars else None
        
        # Load old state
        old_state = None
        old_state_json = alert.get("last_state")
        if old_state_json:
            try:
                old_state = json.loads(old_state_json)
            except Exception:
                old_state = None
        
        # Detect changes
        triggered_events = _detect_changes(alert_type, old_state, new_state, current_price)
        
        # Update alert state in DB
        now = datetime.now(timezone.utc).isoformat()
        conn = _get_db()
        try:
            if triggered_events:
                conn.execute(
                    """UPDATE alerts SET last_state = ?, last_checked_at = ?,
                       last_triggered_at = ?, trigger_count = trigger_count + ? WHERE id = ?""",
                    (json.dumps(new_state), now, now, len(triggered_events), alert_id),
                )
                # Log history
                for ev in triggered_events:
                    conn.execute(
                        """INSERT INTO alert_history (alert_id, symbol, event_type, event_desc, old_state, new_state, triggered_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (alert_id, symbol, ev["event_type"], ev["event_desc"],
                         json.dumps(old_state) if old_state else "",
                         json.dumps(new_state), now),
                    )
                conn.commit()
                
                # Send Telegram
                await _send_telegram_alert(symbol, triggered_events, current_price)
                logger.info(f"[alerts] TRIGGERED {symbol}: {[e['event_type'] for e in triggered_events]}")
            else:
                # Chỉ update last_checked_at + state nếu state thay đổi
                conn.execute(
                    "UPDATE alerts SET last_state = ?, last_checked_at = ? WHERE id = ?",
                    (json.dumps(new_state), now, alert_id),
                )
                conn.commit()
        finally:
            conn.close()
        
        return len(triggered_events)
    except asyncio.TimeoutError:
        logger.warning(f"[alerts] timeout {symbol}")
        return 0
    except SystemExit:
        # vnstock rate limit
        logger.warning(f"[alerts] rate limit hit at {symbol}")
        return 0
    except Exception as e:
        logger.exception(f"[alerts] check {symbol} fail: {e}")
        return 0


async def check_all_alerts() -> Dict[str, int]:
    """Check tất cả alerts enabled. Trả về stats."""
    alerts = list_alerts(enabled_only=True)
    if not alerts:
        return {"checked": 0, "triggered": 0}
    
    logger.info(f"[alerts] Checking {len(alerts)} enabled alerts")
    total_triggered = 0
    checked = 0
    
    # Check sequentially với sleep để tránh rate limit
    for alert in alerts:
        n = await check_one_alert(alert)
        total_triggered += n
        checked += 1
        await asyncio.sleep(2.0)   # 30 alerts/phút - an toàn
    
    logger.info(f"[alerts] Done: checked {checked}, triggered {total_triggered}")
    return {"checked": checked, "triggered": total_triggered}


def _is_market_hours() -> bool:
    """Kiểm tra có phải giờ giao dịch VN (T2-T6, 9h-15h)."""
    now = datetime.now()
    # T2-T6
    if now.weekday() >= 5:
        return False
    # 9h - 15h VN time
    h = now.hour
    return 9 <= h <= 15


_LOOP_TASK = None


async def alert_loop():
    """Background loop chạy mỗi 15 phút."""
    logger.info("[alerts] Background loop started")
    while True:
        try:
            if _is_market_hours():
                await check_all_alerts()
            else:
                logger.debug("[alerts] Skip - outside market hours")
        except Exception as e:
            logger.exception(f"[alerts] loop error: {e}")
        # Sleep 15 phút
        await asyncio.sleep(15 * 60)


def start_alert_loop():
    """Khởi tạo background task. Gọi từ main.py lifespan."""
    global _LOOP_TASK
    if _LOOP_TASK is None or _LOOP_TASK.done():
        init_db()
        _LOOP_TASK = asyncio.create_task(alert_loop())
        logger.info("[alerts] Background task scheduled")
    return _LOOP_TASK
