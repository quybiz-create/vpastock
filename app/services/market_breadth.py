"""
Market Breadth Fear & Greed - Phase 14D
Tính F&G dựa trên ĐỘ RỘNG THỊ TRƯỜNG (tất cả mã) thay vì chỉ VNINDEX.

5 chỉ số chính:
1. A/D Ratio (25%):     (số mã tăng - số mã giảm) / tổng
2. %>MA20 (25%):        % mã có giá > MA20
3. %>MA50 (20%):        % mã có giá > MA50
4. A/D Momentum (15%):  Trung bình A/D 5 ngày
5. MA20 Trend (15%):    Trend của index MA20 (slope 5 ngày)

Universe (~200 mã):
- Tất cả watchlist symbols (DB)
- + Sector leaders (SECTOR_STOCKS)
- Dedup
"""
from __future__ import annotations
import asyncio
import math
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple
from loguru import logger
import pandas as pd


# Cache 5 phút
class _RateLimitException(Exception):
    """Internal: stop scan when rate limited."""
    pass


_BREADTH_CACHE: Dict[str, Any] = {"data": None, "at": 0}
_BREADTH_CACHE_TTL = 900   # 15 phút (data không đổi nhiều)


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


# ============================================================
# UNIVERSE BUILDER
# ============================================================

# Top liquid VN stocks - chosen for Breadth scan (60 mã)
# Đại diện ngành đầy đủ + thanh khoản cao = phản ánh tốt sức khỏe TT
DEFAULT_BREADTH_UNIVERSE = [
    # VN30 core (top market cap)
    "VCB", "BID", "CTG", "TCB", "MBB", "VPB", "ACB", "HDB", "STB", "SHB",
    "VIC", "VHM", "VRE", "NVL", "KDH", "DXG", "PDR",
    "HPG", "HSG", "NKG", "MSN", "VNM", "SAB", "MWG", "FPT", "GAS", "PLX",
    "POW", "REE", "GMD", "VJC", "SSI", "VND", "VCI",
    # High liquidity additions  
    "DGC", "DCM", "DPM", "BMP", "VGC", "DGW", "PNJ", "DHG",
    "PVS", "PVD", "BSR", "OIL", "DIG", "CEO", "KBC",
    "TPB", "VIB", "LPB", "EIB", "MSB", "OCB",
    "DBC", "VHC", "ANV", "FRT", "PET",
]

def get_universe_symbols() -> List[str]:
    """Build danh sách mã để scan Breadth.
    
    Strategy:
    - Default: 60 mã top liquid (VN30 + extras đại diện ngành)
    - Tránh scan all watchlist → rate limit
    - Cache 15 phút nên scan 1 lần đủ cho cả phiên
    """
    return list(DEFAULT_BREADTH_UNIVERSE)


# ============================================================
# COMPUTE BREADTH FOR ONE SYMBOL
# ============================================================

async def _compute_one_symbol(symbol: str, start: str, end: str) -> Optional[Dict[str, Any]]:
    """Fetch history + compute breadth metrics cho 1 mã.
    Trả về dict hoặc None nếu lỗi.
    """
    try:
        from app.data.vnstock_client import vnstock_client
        
        df = await asyncio.wait_for(
            vnstock_client.get_history(symbol, start=start, end=end),
            timeout=10.0,
        )
        if df is None or df.empty or len(df) < 30:
            return None
        
        df = df[~df.index.duplicated(keep='last')].sort_index()
        
        # Compute MAs
        df["ma20"] = df["close"].rolling(20).mean()
        df["ma50"] = df["close"].rolling(50).mean()
        
        # Latest values
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last
        
        close_today = float(last["close"])
        close_yest = float(prev["close"])
        ma20 = _safe_float(last.get("ma20"))
        ma50 = _safe_float(last.get("ma50"))
        
        # 5 days ago for momentum
        if len(df) >= 6:
            close_5d_ago = float(df["close"].iloc[-6])
        else:
            close_5d_ago = close_today
        
        # Direction today
        if close_today > close_yest:
            direction = "advance"
        elif close_today < close_yest:
            direction = "decline"
        else:
            direction = "unchanged"
        
        # Direction 5d
        if close_today > close_5d_ago * 1.005:   # > 0.5% lên
            direction_5d = "advance"
        elif close_today < close_5d_ago * 0.995:   # > 0.5% xuống
            direction_5d = "decline"
        else:
            direction_5d = "unchanged"
        
        return {
            "symbol": symbol,
            "close": close_today,
            "direction": direction,
            "direction_5d": direction_5d,
            "above_ma20": ma20 is not None and close_today > ma20,
            "above_ma50": ma50 is not None and close_today > ma50,
            "pct_5d": ((close_today - close_5d_ago) / close_5d_ago * 100) if close_5d_ago > 0 else 0,
        }
    
    except asyncio.TimeoutError:
        logger.debug(f"[breadth] timeout {symbol}")
        return None
    except SystemExit:
        # vnai rate limit
        raise
    except Exception as e:
        logger.debug(f"[breadth] skip {symbol}: {e}")
        return None


# ============================================================
# COMPUTE FULL BREADTH (all symbols)
# ============================================================

async def compute_market_breadth(force_refresh: bool = False) -> Dict[str, Any]:
    """Scan tất cả symbols → tính breadth metrics.
    Cache 5 phút.
    """
    import time as _time
    
    # Check cache
    now = _time.time()
    if not force_refresh and _BREADTH_CACHE["data"] and (now - _BREADTH_CACHE["at"]) < _BREADTH_CACHE_TTL:
        cached = dict(_BREADTH_CACHE["data"])
        cached["cached"] = True
        return cached
    
    universe = get_universe_symbols()
    if not universe:
        return {"error": "Universe rỗng", "total": 0}
    
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    
    logger.info(f"[breadth] Scanning {len(universe)} symbols...")
    start_time = _time.time()
    
    results: List[Dict[str, Any]] = []
    errors_count = 0
    
    # Batch processing - vnstock Community: 60 req/phút = 1 req/giây
    # → BATCH=3 / DELAY=3s = ~1 req/s = SAFE
    BATCH_SIZE = 3
    BATCH_DELAY = 3.0   # giây giữa batches
    
    for i in range(0, len(universe), BATCH_SIZE):
        batch = universe[i:i + BATCH_SIZE]
        
        try:
            batch_results = await asyncio.gather(
                *[_compute_one_symbol(sym, start, end) for sym in batch],
                return_exceptions=True,
            )
            
            for r in batch_results:
                if isinstance(r, dict):
                    results.append(r)
                elif isinstance(r, (SystemExit, asyncio.CancelledError)):
                    logger.warning(f"[breadth] Rate limit/cancel at batch {i}, stopping with {len(results)} symbols")
                    raise _RateLimitException()
                else:
                    errors_count += 1
        except _RateLimitException:
            logger.warning(f"[breadth] Partial scan: {len(results)}/{len(universe)} symbols")
            break
        except (SystemExit, asyncio.CancelledError):
            logger.warning(f"[breadth] CancelledError at batch {i}, partial result")
            break
        except Exception as e:
            logger.warning(f"[breadth] Batch {i} fail: {e}")
            errors_count += BATCH_SIZE
        
        # Sleep giữa batches
        if i + BATCH_SIZE < len(universe):
            await asyncio.sleep(BATCH_DELAY)
    
    elapsed = _time.time() - start_time
    logger.info(f"[breadth] Scanned {len(results)}/{len(universe)} symbols in {elapsed:.1f}s, errors={errors_count}")
    
    if len(results) < 10:
        # Quá ít data → coi như fail
        return {
            "error": f"Chỉ lấy được {len(results)}/{len(universe)} mã. Vnstock rate limit. Thử lại sau 1 phút.",
            "total": len(universe),
            "got": len(results),
        }
    
    if len(results) < len(universe) * 0.5:
        # Partial - cảnh báo nhưng vẫn dùng được
        logger.warning(f"[breadth] PARTIAL: {len(results)}/{len(universe)} - data tin cậy giảm")
    
    # Aggregate stats
    total = len(results)
    advance = sum(1 for r in results if r["direction"] == "advance")
    decline = sum(1 for r in results if r["direction"] == "decline")
    unchanged = total - advance - decline
    
    advance_5d = sum(1 for r in results if r["direction_5d"] == "advance")
    decline_5d = sum(1 for r in results if r["direction_5d"] == "decline")
    
    above_ma20 = sum(1 for r in results if r["above_ma20"])
    above_ma50 = sum(1 for r in results if r["above_ma50"])
    
    ad_ratio = advance - decline   # net advance
    ad_pct = (ad_ratio / total * 100) if total > 0 else 0
    
    ad_ratio_5d = advance_5d - decline_5d
    ad_pct_5d = (ad_ratio_5d / total * 100) if total > 0 else 0
    
    pct_above_ma20 = (above_ma20 / total * 100) if total > 0 else 0
    pct_above_ma50 = (above_ma50 / total * 100) if total > 0 else 0
    
    # MA20 trend của universe (avg MA20 today vs 5d ago - dùng VNINDEX as proxy)
    ma20_trend = await _compute_vnindex_ma20_trend(end)
    
    breadth = {
        "total": total,
        "advance": advance,
        "decline": decline,
        "unchanged": unchanged,
        "ad_ratio": ad_ratio,
        "ad_pct": round(ad_pct, 2),
        "advance_5d": advance_5d,
        "decline_5d": decline_5d,
        "ad_ratio_5d": ad_ratio_5d,
        "ad_pct_5d": round(ad_pct_5d, 2),
        "above_ma20": above_ma20,
        "above_ma50": above_ma50,
        "pct_above_ma20": round(pct_above_ma20, 2),
        "pct_above_ma50": round(pct_above_ma50, 2),
        "ma20_trend_pct": round(ma20_trend, 2),
        "scanned_at": datetime.now().isoformat(),
        "scan_duration_s": round(elapsed, 1),
        "errors": errors_count,
    }
    
    # Cache
    _BREADTH_CACHE["data"] = breadth
    _BREADTH_CACHE["at"] = _time.time()
    
    return breadth


async def _compute_vnindex_ma20_trend(end_date: str) -> float:
    """Tính % thay đổi của MA20 VNINDEX trong 5 ngày qua.
    Dương = trend tăng, âm = trend giảm.
    """
    try:
        from app.data.vnstock_client import vnstock_client
        start = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        df = await asyncio.wait_for(
            vnstock_client.get_history("VNINDEX", start=start, end=end_date),
            timeout=10.0,
        )
        if df is None or df.empty or len(df) < 25:
            return 0.0
        df = df[~df.index.duplicated(keep='last')].sort_index()
        df["ma20"] = df["close"].rolling(20).mean()
        df = df.dropna()
        if len(df) < 6:
            return 0.0
        ma20_today = float(df["ma20"].iloc[-1])
        ma20_5d = float(df["ma20"].iloc[-6])
        if ma20_5d <= 0:
            return 0.0
        return ((ma20_today - ma20_5d) / ma20_5d) * 100
    except Exception as e:
        logger.warning(f"[breadth] ma20_trend fail: {e}")
        return 0.0


# ============================================================
# SCORE NORMALIZATION
# ============================================================

def _score_ad_ratio(ad_pct: float) -> float:
    """A/D Ratio score.
    - ad_pct = -100% (tất cả giảm) → 0 (Fear cực)
    - ad_pct = 0 (50/50) → 50 (neutral)
    - ad_pct = +100% (tất cả tăng) → 100 (Greed cực)
    """
    return max(0.0, min(100.0, 50.0 + ad_pct / 2.0))


def _score_above_ma(pct_above: float) -> float:
    """% mã trên MA score.
    - pct = 0% (không mã nào trên MA) → 0 (Fear cực)
    - pct = 50% → 50 (neutral)
    - pct = 100% (tất cả trên MA) → 100 (Greed cực)
    """
    return max(0.0, min(100.0, pct_above))


def _score_ma20_trend(ma20_trend_pct: float) -> float:
    """MA20 Trend score.
    - -5% → 0 (Fear)
    - 0% → 50 (neutral)
    - +5% → 100 (Greed)
    """
    return max(0.0, min(100.0, 50.0 + (ma20_trend_pct / 5.0) * 50.0))


# ============================================================
# MAIN: COMPUTE FEAR & GREED (Market Breadth)
# ============================================================

async def compute_fear_greed_breadth() -> Dict[str, Any]:
    """Tính F&G theo Market Breadth (chuyên nghiệp hơn VNINDEX-based)."""
    try:
        breadth = await compute_market_breadth()
        
        if "error" in breadth:
            return {
                "score": 50,
                "label": "N/A",
                "error": breadth["error"],
                "components": {},
            }
        
        # Compute subscores
        score_ad = _score_ad_ratio(breadth["ad_pct"])
        score_ma20 = _score_above_ma(breadth["pct_above_ma20"])
        score_ma50 = _score_above_ma(breadth["pct_above_ma50"])
        score_ad_mom = _score_ad_ratio(breadth["ad_pct_5d"])
        score_ma20_trend = _score_ma20_trend(breadth["ma20_trend_pct"])
        
        # Weighted total
        score = (
            score_ad * 0.25
            + score_ma20 * 0.25
            + score_ma50 * 0.20
            + score_ad_mom * 0.15
            + score_ma20_trend * 0.15
        )
        score = round(max(0, min(100, score)), 1)
        
        # Label
        if score < 25:
            label, emoji = "Sợ hãi cực độ", "😱"
        elif score < 45:
            label, emoji = "Sợ hãi", "😨"
        elif score < 55:
            label, emoji = "Trung tính", "😐"
        elif score < 75:
            label, emoji = "Tham lam", "😏"
        else:
            label, emoji = "Tham lam cực độ", "🤑"
        
        result = {
            "score": score,
            "label": label,
            "emoji": emoji,
            "breadth": breadth,
            "components": {
                "ad_ratio": {
                    "value": breadth["ad_ratio"],
                    "value_pct": breadth["ad_pct"],
                    "score": round(score_ad, 1),
                    "weight": 25,
                    "label": "A/D Ratio",
                    "detail": f"{breadth['advance']}↑ / {breadth['decline']}↓",
                },
                "pct_above_ma20": {
                    "value": breadth["pct_above_ma20"],
                    "score": round(score_ma20, 1),
                    "weight": 25,
                    "label": "% > MA20",
                    "detail": f"{breadth['above_ma20']}/{breadth['total']} mã",
                },
                "pct_above_ma50": {
                    "value": breadth["pct_above_ma50"],
                    "score": round(score_ma50, 1),
                    "weight": 20,
                    "label": "% > MA50",
                    "detail": f"{breadth['above_ma50']}/{breadth['total']} mã",
                },
                "ad_momentum": {
                    "value": breadth["ad_ratio_5d"],
                    "value_pct": breadth["ad_pct_5d"],
                    "score": round(score_ad_mom, 1),
                    "weight": 15,
                    "label": "A/D Momentum 5D",
                    "detail": f"{breadth['advance_5d']}↑ / {breadth['decline_5d']}↓ (5 ngày)",
                },
                "ma20_trend": {
                    "value": breadth["ma20_trend_pct"],
                    "score": round(score_ma20_trend, 1),
                    "weight": 15,
                    "label": "MA20 Trend",
                    "detail": f"VNINDEX MA20 {'+' if breadth['ma20_trend_pct'] >= 0 else ''}{breadth['ma20_trend_pct']:.2f}% (5 ngày)",
                },
            },
            "updated_at": datetime.now().isoformat(),
        }
        
        # Persist snapshot
        try:
            from app.services import breadth_history
            breadth_history.save_snapshot(result)
        except Exception as e:
            logger.warning(f"[breadth] history save fail: {e}")
        
        return result
    
    except Exception as e:
        logger.exception(f"[breadth] compute fail: {e}")
        return {
            "score": 50,
            "label": "N/A",
            "error": str(e),
            "components": {},
        }


# Standalone test
if __name__ == "__main__":
    import json
    
    async def _test():
        print("=" * 60)
        print("Testing Market Breadth F&G")
        print("=" * 60)
        result = await compute_fear_greed_breadth()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    
    asyncio.run(_test())
