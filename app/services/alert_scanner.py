"""
Background task scanner alerts.
Chay moi 10 phut, check tat ca active alerts.

Workflow:
1. Query distinct symbols co alert active
2. Fetch current price tu API Phase 1 (/api/stock/{sym}/indicators)
3. So sanh voi threshold tung alert
4. Update triggered_at neu match
"""
from __future__ import annotations
import asyncio
import time
import urllib.request
import json
from datetime import datetime
from typing import Dict, Optional

from loguru import logger
from app.db.database import get_db

# Configuration
SCAN_INTERVAL = 600  # 10 phut
PRICE_CACHE_TTL = 300  # 5 phut
INTERNAL_API = "http://127.0.0.1:8000"

# In-memory price cache (symbol -> (price, timestamp))
_price_cache: Dict[str, tuple] = {}


def _fetch_current_price(symbol: str) -> Optional[float]:
    """
    Fetch gia hien tai cua mot ma CP qua API noi bo Phase 1.
    Cache 5 phut de tranh goi lap.
    """
    now = time.time()
    
    # Check cache
    if symbol in _price_cache:
        price, ts = _price_cache[symbol]
        if now - ts < PRICE_CACHE_TTL:
            return price
    
    # Fetch from internal API
    try:
        url = f"{INTERNAL_API}/api/stock/{symbol}/indicators"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        
        price = data.get("last", {}).get("price")
        if price is None:
            return None
        
        price = float(price)
        _price_cache[symbol] = (price, now)
        return price
    except Exception as e:
        logger.warning(f"[SCANNER] Fetch price {symbol} failed: {e}")
        return None


def _check_trigger(alert_type: str, threshold: float, current: float) -> bool:
    """Kiem tra alert co trigger khong."""
    if alert_type == "price_above":
        return current >= threshold
    elif alert_type == "price_below":
        return current <= threshold
    # pct_change: skip cho Phase 4 (can prev_close)
    return False


async def scan_once():
    """Mot lan scan: check tat ca active alerts."""
    # Step 1: Get distinct symbols co alert active
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT DISTINCT symbol 
            FROM alerts 
            WHERE is_active = 1 AND triggered_at IS NULL
        """)
        symbols = [row["symbol"] for row in cursor.fetchall()]
    
    if not symbols:
        logger.info("[SCANNER] No active alerts to check")
        return
    
    logger.info(f"[SCANNER] Checking {len(symbols)} symbols: {symbols}")
    
    # Step 2: Fetch prices (chay trong thread pool de khong block event loop)
    loop = asyncio.get_event_loop()
    prices = {}
    for sym in symbols:
        price = await loop.run_in_executor(None, _fetch_current_price, sym)
        if price is not None:
            prices[sym] = price
            logger.info(f"[SCANNER] {sym} = {price:,.2f}")
        else:
            logger.warning(f"[SCANNER] {sym} - no price data")
    
    if not prices:
        return
    
    # Step 3: Check each alert
    triggered_count = 0
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT id, user_fp, symbol, alert_type, threshold, note
            FROM alerts 
            WHERE is_active = 1 AND triggered_at IS NULL
        """)
        alerts = cursor.fetchall()
        
        now = datetime.now()
        for alert in alerts:
            sym = alert["symbol"]
            if sym not in prices:
                continue
            
            current = prices[sym]
            
            # Always update last_checked
            conn.execute(
                "UPDATE alerts SET last_checked = ? WHERE id = ?",
                (now, alert["id"]),
            )
            
            if _check_trigger(alert["alert_type"], alert["threshold"], current):
                # Trigger!
                conn.execute(
                    "UPDATE alerts SET triggered_at = ? WHERE id = ?",
                    (now, alert["id"]),
                )
                triggered_count += 1
                logger.success(
                    f"[TRIGGERED] Alert #{alert['id']} {sym} "
                    f"{alert['alert_type']} {alert['threshold']} "
                    f"(current: {current:,.2f}) note: {alert['note']}"
                )
    
    if triggered_count > 0:
        logger.success(f"[SCANNER] Triggered {triggered_count} alerts!")


async def scanner_loop():
    """
    Loop chay vinh vien.
    Goi tu app.main:lifespan luc startup.
    """
    logger.info(f"[SCANNER] Started. Interval: {SCAN_INTERVAL}s ({SCAN_INTERVAL//60} min)")
    
    # Wait 30s sau khi startup roi moi scan lan dau
    await asyncio.sleep(30)
    
    while True:
        try:
            await scan_once()
        except asyncio.CancelledError:
            logger.info("[SCANNER] Cancelled, exiting loop")
            raise
        except Exception as e:
            logger.error(f"[SCANNER] Error: {e}")
        
        await asyncio.sleep(SCAN_INTERVAL)


# Run standalone for testing: python -m app.services.alert_scanner
if __name__ == "__main__":
    print("Running scan_once() standalone...")
    asyncio.run(scan_once())
    print("Done!")