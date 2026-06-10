"""
Market Breadth Fear & Greed - Phase 14D (FireAnt edition)

Reuses FireAnt API (đã có sẵn cho news) để fetch historical quotes
→ Bypass vnstock 60 req/phút limit
→ Scan được nhiều mã (100-200+) mà không bị kill backend

Endpoint: GET /symbols/{ticker}/historical-quotes?startDate=...&endDate=...
Auth: Bearer token (FIREANT_TOKEN env)

Output format giống Phase 14D vnstock version (compatible với frontend).
"""
from __future__ import annotations
import asyncio
import os
import time as _time
import math
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set
from loguru import logger
import httpx


_FIREANT_BASE = "https://restv2.fireant.vn"

# Cache TTL 15 phút (data không đổi nhiều)
_BREADTH_CACHE: Dict[str, Any] = {"data": None, "at": 0}
_BREADTH_CACHE_TTL = 900


# ============================================================
# UNIVERSE: 100 mã top liquid VN
# ============================================================
DEFAULT_BREADTH_UNIVERSE = [
    # Banks (18)
    "VCB", "BID", "CTG", "TCB", "MBB", "VPB", "ACB", "HDB", "STB", "SHB",
    "TPB", "VIB", "LPB", "EIB", "MSB", "OCB", "NAB", "VAB",
    # Real Estate (15)
    "VIC", "VHM", "VRE", "NVL", "KDH", "DXG", "PDR", "NLG", "DIG", "CEO",
    "KBC", "ITA", "HDC", "AGG", "HDG",
    # Basic Resources / Steel (8)
    "HPG", "HSG", "NKG", "POM", "TVN", "TLH", "VGS", "SMC",
    # Food & Beverage (10)
    "VNM", "MSN", "SAB", "MCH", "VHC", "SBT", "DBC", "KDC", "ANV", "BAF",
    # Oil & Gas (7)
    "GAS", "PLX", "BSR", "OIL", "PVD", "PVS", "PVT",
    # Retail / Tech (10)
    "MWG", "FRT", "DGW", "PNJ", "PET", "FPT", "CMG", "ELC", "ITD", "SAM",
    # Financial Services (8)
    "SSI", "VCI", "VND", "HCM", "SHS", "VIX", "FTS", "MBS",
    # Utilities (7)
    "POW", "REE", "NT2", "GEG", "PC1", "VSH", "TBC",
    # Industrial / Construction (10)
    "GMD", "VSC", "HAH", "VOS", "VTP", "VCG", "CTD", "HT1", "HBC", "HUT",
    # Chemicals / Health (7)
    "DGC", "DCM", "DPM", "BMP", "VGC", "DHG", "IMP",
]


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


def get_universe_symbols() -> List[str]:
    """Build universe gồm:
    - Top 100 mã liquid (built-in)
    - + Tất cả mã trong watchlist DB (dedup)
    """
    symbols: Set[str] = set(DEFAULT_BREADTH_UNIVERSE)
    
    # Thêm từ watchlist DB
    try:
        from app.db.database import get_db
        with get_db() as conn:
            cursor = conn.execute("SELECT DISTINCT symbol FROM watchlist_items")
            for row in cursor.fetchall():
                sym = row["symbol"] if hasattr(row, "keys") else row[0]
                if sym:
                    symbols.add(sym.upper())
    except Exception as e:
        logger.debug(f"[breadth_fa] watchlist load skip: {e}")
    
    symbols.discard("VNINDEX")
    result = sorted(symbols)
    logger.info(f"[breadth_fa] Universe: {len(result)} symbols")
    return result


# ============================================================
# FIREANT API CALL
# ============================================================

def _get_fireant_token() -> Optional[str]:
    return os.environ.get("FIREANT_TOKEN") or None


async def _fetch_fireant_history(
    client: httpx.AsyncClient,
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[List[Dict[str, Any]]]:
    """Gọi FireAnt API lấy historical OHLCV của 1 symbol.
    
    Returns: List of {date, priceClose, priceOpen, priceHigh, priceLow, totalVolume}
             hoặc None nếu fail.
    """
    token = _get_fireant_token()
    if not token:
        return None
    
    url = f"{_FIREANT_BASE}/symbols/{symbol}/historical-quotes"
    params = {
        "startDate": start_date,
        "endDate": end_date,
        "offset": 0,
        "limit": 100,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    
    try:
        r = await client.get(url, params=params, headers=headers, timeout=10.0)
        if r.status_code == 401:
            logger.error(f"[breadth_fa] FireAnt 401 for {symbol} - token expired")
            return None
        if r.status_code == 404:
            logger.debug(f"[breadth_fa] {symbol} not found")
            return None
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        return None
    except httpx.TimeoutException:
        logger.debug(f"[breadth_fa] timeout {symbol}")
        return None
    except Exception as e:
        logger.debug(f"[breadth_fa] skip {symbol}: {e}")
        return None


# ============================================================
# COMPUTE BREADTH FOR ONE SYMBOL
# ============================================================

def _compute_metrics_from_history(symbol: str, history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Từ historical data (list dict), tính các metrics:
    - direction (advance/decline)
    - direction_5d
    - above_ma20, above_ma50
    - pct_5d
    """
    if not history or len(history) < 30:
        return None
    
    # FireAnt trả về theo thứ tự desc (mới nhất trước). Sort asc để dễ tính.
    try:
        sorted_history = sorted(history, key=lambda x: x.get("date", ""))
    except Exception:
        return None
    
    closes = []
    for row in sorted_history:
        c = _safe_float(row.get("priceClose"))
        if c is not None and c > 0:
            closes.append(c)
    
    if len(closes) < 30:
        return None
    
    close_today = closes[-1]
    close_yest = closes[-2] if len(closes) >= 2 else close_today
    close_5d_ago = closes[-6] if len(closes) >= 6 else close_today
    
    # MA20, MA50
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
    
    # Direction today
    if close_today > close_yest:
        direction = "advance"
    elif close_today < close_yest:
        direction = "decline"
    else:
        direction = "unchanged"
    
    # Direction 5d (threshold 0.5% để bỏ noise)
    if close_today > close_5d_ago * 1.005:
        direction_5d = "advance"
    elif close_today < close_5d_ago * 0.995:
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


# ============================================================
# COMPUTE FULL BREADTH (all symbols, parallel via FireAnt)
# ============================================================

async def compute_market_breadth(force_refresh: bool = False) -> Dict[str, Any]:
    """Scan all symbols qua FireAnt → tính breadth.
    
    FireAnt cho phép parallel cao hơn vnstock (~20 req/giây OK).
    Cache 15 phút.
    """
    # Cache check
    now = _time.time()
    if not force_refresh and _BREADTH_CACHE["data"] and (now - _BREADTH_CACHE["at"]) < _BREADTH_CACHE_TTL:
        cached = dict(_BREADTH_CACHE["data"])
        cached["cached"] = True
        return cached
    
    token = _get_fireant_token()
    if not token:
        return {
            "error": "FIREANT_TOKEN không có trong .env. Vui lòng config token.",
            "total": 0,
        }
    
    universe = get_universe_symbols()
    if not universe:
        return {"error": "Universe rỗng", "total": 0}
    
    # Date range: lấy 90 ngày để có đủ data tính MA50
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    
    logger.info(f"[breadth_fa] Scanning {len(universe)} symbols via FireAnt...")
    start_time = _time.time()
    
    results: List[Dict[str, Any]] = []
    errors_count = 0
    
    # FireAnt thoáng hơn vnstock → có thể parallel cao hơn
    # 15 mã/batch × 0.3s delay = 50 req/s (an toàn)
    BATCH_SIZE = 15
    BATCH_DELAY = 0.3
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        for i in range(0, len(universe), BATCH_SIZE):
            batch = universe[i:i + BATCH_SIZE]
            
            try:
                # Parallel fetch batch
                batch_histories = await asyncio.gather(
                    *[_fetch_fireant_history(client, sym, start_date, end_date) for sym in batch],
                    return_exceptions=True,
                )
                
                # Compute metrics từng symbol
                for sym, hist in zip(batch, batch_histories):
                    if isinstance(hist, Exception):
                        errors_count += 1
                        continue
                    if not hist:
                        errors_count += 1
                        continue
                    metrics = _compute_metrics_from_history(sym, hist)
                    if metrics:
                        results.append(metrics)
                    else:
                        errors_count += 1
            
            except Exception as e:
                logger.warning(f"[breadth_fa] Batch {i} fail: {e}")
                errors_count += len(batch)
            
            # Sleep giữa batches
            if i + BATCH_SIZE < len(universe):
                await asyncio.sleep(BATCH_DELAY)
    
    elapsed = _time.time() - start_time
    logger.info(f"[breadth_fa] Scanned {len(results)}/{len(universe)} symbols in {elapsed:.1f}s, errors={errors_count}")
    
    if len(results) < 20:
        return {
            "error": f"Chỉ lấy được {len(results)}/{len(universe)} mã từ FireAnt. Kiểm tra token.",
            "total": len(universe),
            "got": len(results),
        }
    
    # Aggregate stats
    total = len(results)
    advance = sum(1 for r in results if r["direction"] == "advance")
    decline = sum(1 for r in results if r["direction"] == "decline")
    unchanged = total - advance - decline
    
    advance_5d = sum(1 for r in results if r["direction_5d"] == "advance")
    decline_5d = sum(1 for r in results if r["direction_5d"] == "decline")
    
    above_ma20 = sum(1 for r in results if r["above_ma20"])
    above_ma50 = sum(1 for r in results if r["above_ma50"])
    
    ad_ratio = advance - decline
    ad_pct = (ad_ratio / total * 100) if total > 0 else 0
    
    ad_ratio_5d = advance_5d - decline_5d
    ad_pct_5d = (ad_ratio_5d / total * 100) if total > 0 else 0
    
    pct_above_ma20 = (above_ma20 / total * 100) if total > 0 else 0
    pct_above_ma50 = (above_ma50 / total * 100) if total > 0 else 0
    
    # MA20 Trend: tính từ VNINDEX (qua FireAnt)
    ma20_trend = await _compute_vnindex_ma20_trend(start_date, end_date)
    
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
        "data_source": "FireAnt",
    }
    
    _BREADTH_CACHE["data"] = breadth
    _BREADTH_CACHE["at"] = _time.time()
    
    return breadth


async def _compute_vnindex_ma20_trend(start_date: str, end_date: str) -> float:
    """Tính trend MA20 của VNINDEX qua FireAnt."""
    try:
        token = _get_fireant_token()
        if not token:
            return 0.0
        async with httpx.AsyncClient(timeout=10.0) as client:
            hist = await _fetch_fireant_history(client, "VNINDEX", start_date, end_date)
            if not hist or len(hist) < 25:
                return 0.0
            sorted_h = sorted(hist, key=lambda x: x.get("date", ""))
            closes = [_safe_float(r.get("priceClose")) for r in sorted_h]
            closes = [c for c in closes if c is not None and c > 0]
            if len(closes) < 25:
                return 0.0
            # MA20 today vs 5d ago
            ma20_today = sum(closes[-20:]) / 20
            ma20_5d_ago = sum(closes[-25:-5]) / 20 if len(closes) >= 25 else ma20_today
            if ma20_5d_ago <= 0:
                return 0.0
            return ((ma20_today - ma20_5d_ago) / ma20_5d_ago) * 100
    except Exception as e:
        logger.warning(f"[breadth_fa] ma20_trend fail: {e}")
        return 0.0


# ============================================================
# SCORE NORMALIZATION (same as vnstock version)
# ============================================================

def _score_ad_ratio(ad_pct: float) -> float:
    return max(0.0, min(100.0, 50.0 + ad_pct / 2.0))


def _score_above_ma(pct_above: float) -> float:
    return max(0.0, min(100.0, pct_above))


def _score_ma20_trend(ma20_trend_pct: float) -> float:
    return max(0.0, min(100.0, 50.0 + (ma20_trend_pct / 5.0) * 50.0))


# ============================================================
# MAIN: COMPUTE FEAR & GREED (Market Breadth via FireAnt)
# ============================================================

async def compute_fear_greed_breadth() -> Dict[str, Any]:
    """Tính F&G theo Market Breadth qua FireAnt API."""
    try:
        breadth = await compute_market_breadth()
        
        if "error" in breadth:
            return {
                "score": 50,
                "label": "N/A",
                "error": breadth["error"],
                "components": {},
            }
        
        score_ad = _score_ad_ratio(breadth["ad_pct"])
        score_ma20 = _score_above_ma(breadth["pct_above_ma20"])
        score_ma50 = _score_above_ma(breadth["pct_above_ma50"])
        score_ad_mom = _score_ad_ratio(breadth["ad_pct_5d"])
        score_ma20_trend = _score_ma20_trend(breadth["ma20_trend_pct"])
        
        score = (
            score_ad * 0.25
            + score_ma20 * 0.25
            + score_ma50 * 0.20
            + score_ad_mom * 0.15
            + score_ma20_trend * 0.15
        )
        score = round(max(0, min(100, score)), 1)
        
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
            logger.debug(f"[breadth_fa] history save skip: {e}")
        
        return result
    
    except Exception as e:
        logger.exception(f"[breadth_fa] compute fail: {e}")
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
        print("Testing Market Breadth F&G via FireAnt")
        print("=" * 60)
        result = await compute_fear_greed_breadth()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    
    asyncio.run(_test())
