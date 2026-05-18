"""
Scanner service - quet toan thi truong va loc theo preset.

Architecture:
- async concurrent voi semaphore (max 20 song song)
- Cache ket qua 30 phut
- Background pre-scan (sau nay them scheduler)
"""
from __future__ import annotations
from typing import List, Dict, Optional, Literal
from datetime import datetime, timedelta
import asyncio
import math
import pandas as pd
from loguru import logger

from app.data.symbol_list import get_all_symbols
from app.data.vnstock_client import vnstock_client
from app.core.indicators import (
    compute_all,
    is_above_ma,
    is_breaking_ma,
    is_squeeze,
    is_vpa_setup,
    is_strong_trend,
)


PresetType = Literal[
    "above_ma20", "above_ma50", "breaking_ma20",
    "squeeze", "vpa_setup", "strong_trend", "vol_breakout"
]


# Cache ket qua scan
_scan_cache: dict = {}
_cache_ttl_minutes = 30
# Rate limit: Community = 60 req/phut. Throttle de an toan.
_min_interval_seconds = 1.1  # 1.1s/request = max 54 req/phut
_last_request_time = 0.0
_request_lock = asyncio.Lock()

# Trang thai scan dang chay
_scan_status: dict = {
    "running": False,
    "progress": 0,
    "total": 0,
    "started_at": None,
}


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


async def scan_one_symbol(symbol: str) -> Optional[Dict]:
    """
    Quet 1 ma CP, return dict voi indicators.
    Return None neu loi/khong co data.
    """
    try:
        # Lay 200 ngay data (du tinh MA200)
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")

        df = await vnstock_client.get_history(symbol, start=start, end=end)
        if df is None or len(df) < 50:
            return None

        df_full = compute_all(df)
        last = df_full.iloc[-1]
        prev = df_full.iloc[-2] if len(df_full) >= 2 else last

        change_pct = ((last["close"] - prev["close"]) / prev["close"] * 100) if prev["close"] else 0

        return {
            "symbol": symbol,
            "price": float(last["close"]),
            "change_pct": _safe_float(change_pct),
            "volume": int(last["volume"]),
            "ma20": _safe_float(last.get("ma20")),
            "ma50": _safe_float(last.get("ma50")),
            "ma200": _safe_float(last.get("ma200")),
            "rsi": _safe_float(last.get("rsi")),
            "adx": _safe_float(last.get("adx")),
            "plus_di": _safe_float(last.get("plus_di")),
            "minus_di": _safe_float(last.get("minus_di")),
            "vol_ratio": _safe_float(last.get("vol_ratio")),
            "vpa": str(last.get("vpa", "Normal")),
            "_df": df_full,  # Giu de apply filter, se xoa khi return ra ngoai
        }
    except Exception as e:
        logger.debug(f"scan_one_symbol loi cho {symbol}: {e}")
        return None


def match_preset(stock: Dict, preset: str) -> bool:
    """
    Ap dung preset filter len ket qua scan_one_symbol.
    """
    df = stock.get("_df")
    if df is None:
        return False
    price = stock["price"]
    
    if preset == "above_ma20":
        return is_above_ma(df, 20)
    
    elif preset == "above_ma50":
        return is_above_ma(df, 50)
    
    elif preset == "breaking_ma20":
        return is_breaking_ma(df, 20)
    
    elif preset == "squeeze":
        return is_squeeze(df, 20)
    
    elif preset == "vpa_setup":
        return is_vpa_setup(df)
    
    elif preset == "strong_trend":
        return is_strong_trend(df)
    
    elif preset == "vol_breakout":
        vol_ratio = stock.get("vol_ratio")
        return vol_ratio is not None and vol_ratio > 2.0
    
    return False


async def scan_with_semaphore(symbol: str, sem: asyncio.Semaphore) -> Optional[Dict]:
    """Wrapper voi throttle de tranh rate limit."""
    global _last_request_time
    async with sem:
        # Throttle: dam bao co _min_interval_seconds giua cac request
        async with _request_lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - _last_request_time
            if elapsed < _min_interval_seconds:
                await asyncio.sleep(_min_interval_seconds - elapsed)
            _last_request_time = asyncio.get_event_loop().time()
        return await scan_one_symbol(symbol)

async def run_scan(
    preset: str = "above_ma20",
    exchange: str = "HOSE",
    max_concurrent: int = 3,
    force_refresh: bool = False,
) -> Dict:
    """
    Quet toan thi truong va loc theo preset.
    
    Args:
        preset: above_ma20, above_ma50, breaking_ma20, squeeze, vpa_setup, strong_trend, vol_breakout
        exchange: HOSE, HNX, ALL
        max_concurrent: So request song song toi da
        force_refresh: Bo cache, scan lai tu dau
    
    Returns:
        Dict voi keys: preset, exchange, scanned, matched, duration_ms, stocks, generated_at
    """
    cache_key = f"{preset}_{exchange}"
    
    # Check cache
    if not force_refresh and cache_key in _scan_cache:
        cached_at, cached_result = _scan_cache[cache_key]
        if datetime.now() - cached_at < timedelta(minutes=_cache_ttl_minutes):
            cached_result["from_cache"] = True
            logger.info(f"Scan cache hit: {cache_key}")
            return cached_result
    
    # Lay danh sach ma
    symbols = await get_all_symbols(exchange)
    total = len(symbols)
    logger.info(f"Bat dau scan {total} ma cho preset={preset}, exchange={exchange}")
    
    # Update status
    _scan_status["running"] = True
    _scan_status["total"] = total
    _scan_status["progress"] = 0
    _scan_status["started_at"] = datetime.now().isoformat()
    
    t_start = datetime.now()
    sem = asyncio.Semaphore(max_concurrent)
    
    # Async scan tat ca
    tasks = [scan_with_semaphore(sym, sem) for sym in symbols]
    
    # Gather voi progress tracking
    results = []
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        r = await coro
        results.append(r)
        _scan_status["progress"] = i
    
    # Loc bo None va apply preset
    valid_stocks = [r for r in results if r is not None]
    matched = [s for s in valid_stocks if match_preset(s, preset)]
    
    # Sap xep theo vol_ratio giam dan (mac dinh)
    matched.sort(key=lambda s: s.get("vol_ratio") or 0, reverse=True)
    
    # Xoa truong "_df" truoc khi return (khong serialize duoc)
    for s in matched:
        s.pop("_df", None)
    
    duration_ms = int((datetime.now() - t_start).total_seconds() * 1000)
    
    result = {
        "preset": preset,
        "exchange": exchange,
        "scanned": len(valid_stocks),
        "total_symbols": total,
        "matched": len(matched),
        "duration_ms": duration_ms,
        "generated_at": datetime.now().isoformat(),
        "from_cache": False,
        "stocks": matched,
    }
    
    # Cache
    _scan_cache[cache_key] = (datetime.now(), result.copy())
    
    # Reset status
    _scan_status["running"] = False
    _scan_status["progress"] = 0
    
    logger.info(
        f"Scan xong: {len(valid_stocks)}/{total} ma valid, "
        f"{len(matched)} ma match preset, {duration_ms}ms"
    )
    
    return result


def get_scan_status() -> Dict:
    """Tra ve trang thai scan hien tai (cho progress UI)."""
    return _scan_status.copy()