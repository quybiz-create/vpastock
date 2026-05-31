"""
Market Overview module - Phase 7 + 8D + 8E
Provides:
- Fear & Greed Index (custom computed) + history (8D)
- Sector Heatmap (top sectors by % change)
- Stocks per sector (8E)
"""
from __future__ import annotations
import math
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from loguru import logger


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
# FEAR & GREED INDEX - CUSTOM FORMULA
# ============================================================

async def compute_fear_greed() -> Dict[str, Any]:
    """Compute Fear & Greed Index from VNINDEX indicators.
    Side effect (Phase 8D): persists snapshot to SQLite history."""
    try:
        from app.data.vnstock_client import vnstock_client
        from app.core.indicators import compute_all
        
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
        df = await vnstock_client.get_history("VNINDEX", start=start, end=end)
        
        if df is None or df.empty:
            return {"score": 50, "label": "N/A", "components": {}, "error": "No data"}
        
        df = df[~df.index.duplicated(keep='last')]
        df = df.sort_index()
        df_full = compute_all(df)
        df_full = df_full.dropna(subset=["close"])
        
        if len(df_full) < 20:
            return {"score": 50, "label": "N/A", "components": {}, "error": "Insufficient data"}
        
        result = _calc_fg_from_df(df_full)

        # === Phase 8D: persist snapshot ===
        try:
            from app.services import fg_history
            fg_history.save_snapshot(result)
        except Exception as e:
            logger.warning(f"[market] fg_history save_snapshot failed (non-fatal): {e}")

        return result
    except Exception as e:
        logger.exception(f"Fear&Greed compute fail: {e}")
        return {"score": 50, "label": "N/A", "error": str(e), "components": {}}


def _calc_fg_from_df(df_full) -> Dict[str, Any]:
    """Pure calculation from prepared DataFrame."""
    last = df_full.iloc[-1]
    close_now = float(last["close"])
    
    rsi = _safe_float(last.get("rsi"))
    rsi_score = 50.0 if rsi is None else max(0, min(100, rsi))
    
    ma200 = _safe_float(last.get("ma200"))
    if ma200 is None or ma200 <= 0:
        ma200 = _safe_float(last.get("ma50")) or close_now
    pct_above_ma = ((close_now - ma200) / ma200) * 100 if ma200 > 0 else 0
    ma_score = max(0, min(100, 50 + (pct_above_ma / 15) * 50))
    
    vol_ratio = _safe_float(last.get("vol_ratio")) or 1.0
    if vol_ratio < 0.5:
        vol_score = 30
    elif vol_ratio < 1.0:
        vol_score = 30 + (vol_ratio - 0.5) * 40
    elif vol_ratio < 1.5:
        vol_score = 50 + (vol_ratio - 1.0) * 40
    else:
        vol_score = min(85, 70 + (vol_ratio - 1.5) * 15)
    
    recent_atr = df_full["close"].pct_change().rolling(14).std().iloc[-1] * 100
    avg_atr = df_full["close"].pct_change().rolling(60).std().iloc[-1] * 100
    atr_ratio = None
    if recent_atr and avg_atr and avg_atr > 0:
        atr_ratio = recent_atr / avg_atr
        vol_score_atr = max(20, min(80, 70 - (atr_ratio - 0.5) * 30))
    else:
        vol_score_atr = 50
    
    pct_5d = None
    if len(df_full) >= 5:
        close_5d_ago = float(df_full["close"].iloc[-5])
        pct_5d = ((close_now - close_5d_ago) / close_5d_ago) * 100
        mom_score = max(0, min(100, 50 + (pct_5d / 5) * 50))
    else:
        mom_score = 50
    
    score = (
        rsi_score * 0.30 + ma_score * 0.25 + vol_score * 0.20 +
        vol_score_atr * 0.15 + mom_score * 0.10
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
    
    return {
        "score": score,
        "label": label,
        "emoji": emoji,
        "vnindex": {
            "value": round(close_now, 2),
            "ma200": round(ma200, 2) if ma200 else None,
            "pct_above_ma": round(pct_above_ma, 2),
        },
        "components": {
            "rsi": {"value": round(rsi, 1) if rsi else None, "score": round(rsi_score, 1), "weight": 30, "label": "RSI(14)"},
            "ma200": {"value": round(pct_above_ma, 2), "score": round(ma_score, 1), "weight": 25, "label": "Cách MA200"},
            "volume": {"value": round(vol_ratio, 2), "score": round(vol_score, 1), "weight": 20, "label": "Vol/MA20"},
            "volatility": {"value": round(atr_ratio, 2) if atr_ratio else None, "score": round(vol_score_atr, 1), "weight": 15, "label": "Biến động"},
            "momentum": {"value": round(pct_5d, 2) if pct_5d is not None else None, "score": round(mom_score, 1), "weight": 10, "label": "Momentum 5D"},
        },
        "updated_at": datetime.now().isoformat(),
    }


# ============================================================
# SECTOR HEATMAP + STOCKS PER SECTOR (Phase 8E)
# ============================================================
SECTOR_NAMES = {
    "Banks": "🏦 Ngân hàng",
    "Real Estate": "🏘️ Bất động sản",
    "Basic Resources": "🏗️ Tài nguyên cơ bản",
    "Construction & Materials": "🏭 Xây dựng & VLXD",
    "Food & Beverage": "🍔 Thực phẩm & Đồ uống",
    "Oil & Gas": "⛽ Dầu khí",
    "Industrial Goods & Services": "🏭 Công nghiệp",
    "Retail": "🛒 Bán lẻ",
    "Technology": "💻 Công nghệ",
    "Utilities": "💡 Tiện ích",
    "Personal & Household Goods": "🏠 Hàng tiêu dùng",
    "Insurance": "🛡️ Bảo hiểm",
    "Financial Services": "💰 Dịch vụ tài chính",
    "Travel & Leisure": "✈️ Du lịch & Giải trí",
    "Health Care": "💊 Y tế",
    "Telecommunications": "📡 Viễn thông",
    "Chemicals": "🧪 Hóa chất",
    "Automobiles & Parts": "🚗 Ô tô",
    "Media": "📺 Truyền thông",
}

# Top tickers per sector (representative leaders) - 3 đầu để tính heatmap
SECTOR_LEADERS = {
    "Banks": ["VCB", "BID", "CTG"],
    "Real Estate": ["VHM", "VIC", "DXG"],
    "Basic Resources": ["HPG", "HSG", "NKG"],
    "Construction & Materials": ["VCG", "CTD", "HT1"],
    "Food & Beverage": ["VNM", "MSN", "SAB"],
    "Oil & Gas": ["GAS", "PLX", "BSR"],
    "Retail": ["MWG", "FRT", "DGW"],
    "Technology": ["FPT", "CMG", "ELC"],
    "Financial Services": ["SSI", "VCI", "VND"],
    "Utilities": ["POW", "REE", "NT2"],
}

# === Phase 8E: Danh sách MỞ RỘNG mã con theo ngành ===
# (top mã vốn hóa / thanh khoản trên HOSE/HNX, dùng cho expand panel)
SECTOR_STOCKS = {
    "Banks": ["VCB", "BID", "CTG", "TCB", "MBB", "VPB", "ACB", "HDB", "STB", "TPB", "VIB", "SHB", "LPB", "EIB", "MSB", "OCB", "NAB", "VAB"],
    "Real Estate": ["VHM", "VIC", "VRE", "NVL", "KDH", "DXG", "PDR", "NLG", "DIG", "CEO", "KBC", "ITA", "HDC", "AGG", "HDG", "SCR", "TCH", "HPX"],
    "Basic Resources": ["HPG", "HSG", "NKG", "POM", "TVN", "TLH", "VGS", "SMC", "VPG"],
    "Construction & Materials": ["VCG", "CTD", "HT1", "HBC", "HUT", "C4G", "LCG", "FCN", "BCC", "BMP", "VGC", "PHC", "VLB"],
    "Food & Beverage": ["VNM", "MSN", "SAB", "MCH", "VHC", "SBT", "DBC", "KDC", "ANV", "BAF", "ASM", "FMC", "PAN", "TNG"],
    "Oil & Gas": ["GAS", "PLX", "BSR", "OIL", "PVD", "PVS", "PVT", "PVC", "PVB"],
    "Retail": ["MWG", "FRT", "DGW", "PNJ", "PET", "SVC"],
    "Technology": ["FPT", "CMG", "ELC", "ITD", "SAM", "SGT", "ICT"],
    "Financial Services": ["SSI", "VCI", "VND", "HCM", "SHS", "VIX", "FTS", "MBS", "BVS", "AGR", "CTS", "ORS", "TVS", "BSI", "APS"],
    "Utilities": ["POW", "REE", "NT2", "GEG", "HDG", "PC1", "VSH", "TBC", "TMP", "CHP", "SBA"],
    "Industrial Goods & Services": ["GMD", "VSC", "HAH", "VOS", "VTP", "PHP", "SCS", "ACV"],
    "Personal & Household Goods": ["PNJ", "GIL", "TNG", "TCM", "STK", "MSH", "EVE"],
    "Insurance": ["BVH", "BIC", "MIG", "VNR", "PVI", "BMI"],
    "Health Care": ["DHG", "IMP", "DBD", "DCL", "DMC", "PMC", "TRA"],
    "Travel & Leisure": ["VJC", "HVN", "SCS", "OCH", "VTR"],
    "Chemicals": ["DCM", "DPM", "DGC", "BFC", "VAF", "CSV", "LAS"],
    "Telecommunications": ["VGI", "ELC", "VTP", "CMG"],
    "Automobiles & Parts": ["TMT", "HAX", "VEA", "DRC", "SRC", "CSM"],
    "Media": ["YEG", "VNG"],
}


class _RateLimitStop(Exception):
    """Internal signal to stop fetching when rate limited."""
    pass


# In-memory cache
_CACHE = {"fg": None, "fg_at": 0, "sectors": None, "sectors_at": 0,
          "sector_stocks": {}, "sector_stocks_at": {}}
_CACHE_TTL = 300   # giây
_STOCK_CACHE_TTL = 180   # giây cho list stocks (ngắn hơn để cập nhật giá thường xuyên)


async def compute_sector_heatmap() -> Dict[str, Any]:
    """Compute % change for top sectors using their leader stocks."""
    import time as _time
    
    now = _time.time()
    if _CACHE["sectors"] and (now - _CACHE["sectors_at"]) < _CACHE_TTL:
        cached = dict(_CACHE["sectors"])
        cached["cached"] = True
        return cached
    
    try:
        from app.data.vnstock_client import vnstock_client
        
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        
        sectors_result = []
        
        for sector_key, tickers in SECTOR_LEADERS.items():
            sector_name = SECTOR_NAMES.get(sector_key, sector_key)
            pct_changes = []
            tickers_used = []
            
            for ticker in tickers[:2]:
                try:
                    await asyncio.sleep(0.5)
                    df = await asyncio.wait_for(
                        vnstock_client.get_history(ticker, start=start, end=end),
                        timeout=8.0
                    )
                    if df is None or df.empty or len(df) < 2:
                        continue
                    df = df[~df.index.duplicated(keep='last')].sort_index()
                    if len(df) >= 2:
                        close_today = float(df["close"].iloc[-1])
                        close_prev = float(df["close"].iloc[-2])
                        if close_prev > 0:
                            pct = ((close_today - close_prev) / close_prev) * 100
                            pct_changes.append(pct)
                            tickers_used.append({
                                "ticker": ticker,
                                "price": round(close_today, 2),
                                "pct": round(pct, 2),
                            })
                except asyncio.TimeoutError:
                    logger.debug(f"Timeout {ticker}")
                    continue
                except SystemExit as se:
                    logger.warning(f"Rate limit hit at {ticker}: {se}. Stopping sector fetch.")
                    raise _RateLimitStop()
                except Exception as e:
                    logger.debug(f"Skip {ticker}: {e}")
                    continue
            
            if pct_changes:
                avg_pct = sum(pct_changes) / len(pct_changes)
                # Phase 8E: số mã tổng trong ngành (để frontend hint user)
                total_count = len(SECTOR_STOCKS.get(sector_key, tickers))
                sectors_result.append({
                    "key": sector_key,
                    "name": sector_name,
                    "avg_pct": round(avg_pct, 2),
                    "leaders_count": len(tickers_used),
                    "stocks_count": total_count,
                    "leaders": tickers_used,
                })
        
        sectors_result.sort(key=lambda x: x["avg_pct"], reverse=True)
        
        result = {
            "sectors": sectors_result,
            "updated_at": datetime.now().isoformat(),
            "total_sectors": len(sectors_result),
        }
        if len(sectors_result) >= 8:
            _CACHE["sectors"] = result
            _CACHE["sectors_at"] = _time.time()
        return result
    except _RateLimitStop:
        sectors_result.sort(key=lambda x: x["avg_pct"], reverse=True)
        return {
            "sectors": sectors_result,
            "updated_at": datetime.now().isoformat(),
            "total_sectors": len(sectors_result),
            "partial": True,
            "note": "Dữ liệu một phần do giới hạn API",
        }
    except Exception as e:
        logger.exception(f"Sector heatmap fail: {e}")
        return {"sectors": [], "error": str(e)}


# ============================================================
# Phase 8E: Lấy tất cả mã trong 1 ngành (giá + %)
# ============================================================
async def _fetch_one_stock(ticker: str, start: str, end: str) -> Optional[Dict[str, Any]]:
    """Helper: fetch 1 ticker, return dict {ticker, price, pct, volume} or None."""
    try:
        from app.data.vnstock_client import vnstock_client
        df = await asyncio.wait_for(
            vnstock_client.get_history(ticker, start=start, end=end),
            timeout=6.0
        )
        if df is None or df.empty or len(df) < 2:
            return None
        df = df[~df.index.duplicated(keep='last')].sort_index()
        if len(df) < 2:
            return None
        close_today = float(df["close"].iloc[-1])
        close_prev = float(df["close"].iloc[-2])
        if close_prev <= 0:
            return None
        pct = ((close_today - close_prev) / close_prev) * 100
        volume = int(df["volume"].iloc[-1]) if "volume" in df.columns else None
        return {
            "ticker": ticker,
            "price": round(close_today, 2),
            "pct": round(pct, 2),
            "volume": volume,
        }
    except asyncio.TimeoutError:
        logger.debug(f"[sector_stocks] timeout {ticker}")
        return None
    except SystemExit as se:
        # vnai sys.exit khi rate limit
        logger.warning(f"[sector_stocks] rate limit {ticker}: {se}")
        raise _RateLimitStop()
    except Exception as e:
        logger.debug(f"[sector_stocks] skip {ticker}: {e}")
        return None


async def get_sector_stocks(sector_key: str) -> Dict[str, Any]:
    """Lấy tất cả mã trong ngành với giá + %.
    Cache 3 phút theo sector_key."""
    import time as _time
    
    if sector_key not in SECTOR_STOCKS:
        return {
            "sector": sector_key,
            "stocks": [],
            "error": f"Unknown sector: {sector_key}",
            "available": list(SECTOR_STOCKS.keys()),
        }
    
    # Per-sector cache
    now = _time.time()
    cached_at = _CACHE["sector_stocks_at"].get(sector_key, 0)
    if (now - cached_at) < _STOCK_CACHE_TTL and sector_key in _CACHE["sector_stocks"]:
        cached = dict(_CACHE["sector_stocks"][sector_key])
        cached["cached"] = True
        return cached
    
    tickers = SECTOR_STOCKS[sector_key]
    sector_name = SECTOR_NAMES.get(sector_key, sector_key)
    
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    
    stocks: List[Dict[str, Any]] = []
    partial = False
    
    # Fetch tuần tự với delay nhỏ (vnstock dễ rate-limit khi parallel)
    try:
        for tk in tickers:
            await asyncio.sleep(0.35)
            res = await _fetch_one_stock(tk, start, end)
            if res:
                stocks.append(res)
    except _RateLimitStop:
        partial = True
        logger.warning(f"[sector_stocks] {sector_key}: partial due to rate limit ({len(stocks)}/{len(tickers)})")
    except Exception as e:
        logger.exception(f"[sector_stocks] {sector_key} unexpected: {e}")
    
    # Sort theo % giảm dần (tăng nhất lên đầu)
    stocks.sort(key=lambda x: x["pct"], reverse=True)
    
    # Tính trung bình ngành
    if stocks:
        avg_pct = round(sum(s["pct"] for s in stocks) / len(stocks), 2)
        winners = sum(1 for s in stocks if s["pct"] > 0)
        losers = sum(1 for s in stocks if s["pct"] < 0)
        flat = sum(1 for s in stocks if s["pct"] == 0)
    else:
        avg_pct = 0.0
        winners = losers = flat = 0
    
    result = {
        "sector": sector_key,
        "sector_name": sector_name,
        "stocks": stocks,
        "stats": {
            "total": len(stocks),
            "winners": winners,
            "losers": losers,
            "flat": flat,
            "avg_pct": avg_pct,
        },
        "updated_at": datetime.now().isoformat(),
    }
    if partial:
        result["partial"] = True
        result["note"] = "Một số mã chưa lấy được do giới hạn API"
    
    # Cache nếu có ít nhất 50% data
    if len(stocks) >= max(3, len(tickers) // 2):
        _CACHE["sector_stocks"][sector_key] = result
        _CACHE["sector_stocks_at"][sector_key] = _time.time()
    
    return result


# Standalone test
if __name__ == "__main__":
    import json
    
    async def _test():
        print("=== SECTOR STOCKS (Banks) ===")
        ss = await get_sector_stocks("Banks")
        print(json.dumps(ss, ensure_ascii=False, indent=2))
    
    asyncio.run(_test())
