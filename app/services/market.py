"""
Market Overview module - Phase 7
Provides:
- Fear & Greed Index (custom computed)
- Sector Heatmap (top sectors by % change)

Phase 8D update: auto-save F&G snapshots into SQLite history.
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
# Score 0-100:
#   0-25: Extreme Fear
#   25-45: Fear
#   45-55: Neutral
#   55-75: Greed
#   75-100: Extreme Greed
#
# Components (weighted):
# 1. RSI (30%): VNINDEX RSI 14-day
#    < 30 = Fear (0), 30-50 = Cautious (25-50)
#    50-70 = Greed (50-75), > 70 = Extreme Greed (75-100)
# 2. Price vs MA200 (25%): %above
#    < -10% = Extreme Fear, > 10% = Extreme Greed
# 3. Volume (20%): Volume vs MA20
#    < 0.7x = Low conviction (Fear), > 1.3x = High conviction
# 4. Volatility (15%): ATR vs avg
#    Higher ATR = Fear (volatility spike)
# 5. Momentum (10%): 5-day price change
# ============================================================

async def compute_fear_greed() -> Dict[str, Any]:
    """Compute Fear & Greed Index from VNINDEX indicators.
    
    Side effect (Phase 8D): persists the result into SQLite history
    (idempotent within 25 minutes to dedupe rapid calls)."""
    try:
        from app.data.vnstock_client import vnstock_client
        from app.core.indicators import compute_all
        
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
        df = await vnstock_client.get_history("VNINDEX", start=start, end=end)
        
        if df is None or df.empty:
            return {"score": 50, "label": "N/A", "components": {}, "error": "No data"}
        
        # Dedupe + clean
        df = df[~df.index.duplicated(keep='last')]
        df = df.sort_index()
        df_full = compute_all(df)
        df_full = df_full.dropna(subset=["close"])
        
        if len(df_full) < 20:
            return {"score": 50, "label": "N/A", "components": {}, "error": "Insufficient data"}
        
        result = _calc_fg_from_df(df_full)

        # === Phase 8D: persist snapshot to history (best-effort, never fail compute) ===
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
    
    # === Component 1: RSI (30%) ===
    rsi = _safe_float(last.get("rsi"))
    rsi_score = 50.0 if rsi is None else max(0, min(100, rsi))
    
    # === Component 2: Price vs MA200 (25%) ===
    ma200 = _safe_float(last.get("ma200"))
    if ma200 is None or ma200 <= 0:
        ma200 = _safe_float(last.get("ma50")) or close_now
    pct_above_ma = ((close_now - ma200) / ma200) * 100 if ma200 > 0 else 0
    ma_score = max(0, min(100, 50 + (pct_above_ma / 15) * 50))
    
    # === Component 3: Volume vs MA20 (20%) ===
    vol_ratio = _safe_float(last.get("vol_ratio")) or 1.0
    if vol_ratio < 0.5:
        vol_score = 30
    elif vol_ratio < 1.0:
        vol_score = 30 + (vol_ratio - 0.5) * 40
    elif vol_ratio < 1.5:
        vol_score = 50 + (vol_ratio - 1.0) * 40
    else:
        vol_score = min(85, 70 + (vol_ratio - 1.5) * 15)
    
    # === Component 4: ATR/Volatility (15%) - inverse ===
    recent_atr = df_full["close"].pct_change().rolling(14).std().iloc[-1] * 100
    avg_atr = df_full["close"].pct_change().rolling(60).std().iloc[-1] * 100
    atr_ratio = None
    if recent_atr and avg_atr and avg_atr > 0:
        atr_ratio = recent_atr / avg_atr
        vol_score_atr = max(20, min(80, 70 - (atr_ratio - 0.5) * 30))
    else:
        vol_score_atr = 50
    
    # === Component 5: Momentum 5-day (10%) ===
    pct_5d = None
    if len(df_full) >= 5:
        close_5d_ago = float(df_full["close"].iloc[-5])
        pct_5d = ((close_now - close_5d_ago) / close_5d_ago) * 100
        mom_score = max(0, min(100, 50 + (pct_5d / 5) * 50))
    else:
        mom_score = 50
    
    # === Total weighted ===
    score = (
        rsi_score * 0.30 + ma_score * 0.25 + vol_score * 0.20 +
        vol_score_atr * 0.15 + mom_score * 0.10
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
# SECTOR HEATMAP - Top sectors by % change
# ============================================================
# Vietnam sector mapping (ICB lv2 → readable name)
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

# Top tickers per sector (representative leaders) - 3 mã/ngành để nhanh
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


class _RateLimitStop(Exception):
    """Internal signal to stop fetching when rate limited."""
    pass


# In-memory cache (5 phút) để giảm gọi vnstock → tránh rate limit
_CACHE = {"fg": None, "fg_at": 0, "sectors": None, "sectors_at": 0}
_CACHE_TTL = 300  # giây


async def compute_sector_heatmap() -> Dict[str, Any]:
    """Compute % change for top sectors using their leader stocks."""
    import time as _time
    
    # Check cache
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
                    # Delay tránh rate limit vnstock (tăng lên 0.5s)
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
                    # vnai gọi sys.exit khi rate limit - CHẶN không cho kill process
                    logger.warning(f"Rate limit hit at {ticker}: {se}. Stopping sector fetch.")
                    # Trả về kết quả đã có
                    raise _RateLimitStop()
                except Exception as e:
                    logger.debug(f"Skip {ticker}: {e}")
                    continue
            
            if pct_changes:
                avg_pct = sum(pct_changes) / len(pct_changes)
                sectors_result.append({
                    "key": sector_key,
                    "name": sector_name,
                    "avg_pct": round(avg_pct, 2),
                    "leaders_count": len(tickers_used),
                    "leaders": tickers_used,
                })
        
        sectors_result.sort(key=lambda x: x["avg_pct"], reverse=True)
        
        result = {
            "sectors": sectors_result,
            "updated_at": datetime.now().isoformat(),
            "total_sectors": len(sectors_result),
        }
        # Cache nếu fetch đủ (>= 8 ngành)
        if len(sectors_result) >= 8:
            _CACHE["sectors"] = result
            _CACHE["sectors_at"] = _time.time()
        return result
    except _RateLimitStop:
        # Trả về phần đã fetch được trước khi rate limit
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


# Standalone test
if __name__ == "__main__":
    import json
    
    async def _test():
        print("=== FEAR & GREED ===")
        fg = await compute_fear_greed()
        print(json.dumps(fg, ensure_ascii=False, indent=2))
        
        print("\n=== SECTOR HEATMAP ===")
        sh = await compute_sector_heatmap()
        print(json.dumps({"total": sh.get("total_sectors"), "top3": sh.get("sectors", [])[:3]}, ensure_ascii=False, indent=2))
    
    asyncio.run(_test())
