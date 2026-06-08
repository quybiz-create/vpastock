"""
Market Overview module - Phase 7 + 8D + 8E + 14C (fixed F&G)
Provides:
- Fear & Greed Index (custom computed) + history (8D)
- Sector Heatmap (top sectors by % change)
- Stocks per sector (8E)

PHASE 14C FIX (07/06/2026):
- Vol/MA20: bỏ FLOOR 30, vol=0 giờ cho ~10 điểm (cực Fear)
- Volatility: dùng U-curve (low ATR + low vol = Fear, không phải Greed)
- Edge case: vol=0 do data lỗi → fallback 50 neutral
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
# FEAR & GREED INDEX - CUSTOM FORMULA (Phase 14C fixed)
# ============================================================

async def compute_fear_greed() -> Dict[str, Any]:
    """Compute Fear & Greed Index from VNINDEX indicators."""
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


# ============================================================
# PHASE 14C: Sub-score helper functions (fixed logic)
# ============================================================

def _score_rsi(rsi: Optional[float]) -> float:
    """RSI score: 0-100 = identity.
    RSI 30 = Fear extreme, RSI 70 = Greed extreme.
    """
    if rsi is None:
        return 50.0
    return max(0.0, min(100.0, rsi))


def _score_ma200(pct_above_ma: float) -> float:
    """Distance from MA200.
    -15% → 0 (Fear cực)
    0% → 50 (neutral)
    +15% → 100 (Greed cực)
    """
    return max(0.0, min(100.0, 50.0 + (pct_above_ma / 15.0) * 50.0))


def _score_volume(vol_ratio: Optional[float]) -> float:
    """PHASE 14C FIX: Bỏ FLOOR 30 cũ, dùng range rộng 10-90.
    
    Vol/MA20 ratio:
    - 0.0  → 50 (data lỗi, neutral) - không penalize do lỗi tech
    - 0.3  → 15 (cực thấp = chết khoản → Fear extreme)
    - 0.5  → 25 
    - 0.7  → 38
    - 1.0  → 50 (normal)
    - 1.3  → 62
    - 1.5  → 70 (khối lượng tăng = tăng quan tâm = Greed)
    - 2.0  → 82
    - 2.5+ → 90 (volume spike = euphoria/panic - thường top)
    """
    if vol_ratio is None or vol_ratio <= 0:
        # Edge case: data lỗi, không tính Fear oan
        return 50.0
    
    if vol_ratio < 0.3:
        return 10.0 + (vol_ratio / 0.3) * 5.0   # 10 → 15
    elif vol_ratio < 0.7:
        return 15.0 + ((vol_ratio - 0.3) / 0.4) * 23.0   # 15 → 38
    elif vol_ratio < 1.0:
        return 38.0 + ((vol_ratio - 0.7) / 0.3) * 12.0   # 38 → 50
    elif vol_ratio < 1.5:
        return 50.0 + ((vol_ratio - 1.0) / 0.5) * 20.0   # 50 → 70
    elif vol_ratio < 2.5:
        return 70.0 + ((vol_ratio - 1.5) / 1.0) * 20.0   # 70 → 90
    else:
        return 90.0


def _score_volatility(atr_ratio: Optional[float]) -> float:
    """PHASE 14C FIX: Sửa logic ngược.
    
    Cũ: atr thấp → score cao (Greed) - SAI cho VN market
    Mới: U-curve, peak ở atr_ratio = 1.0 (normal)
    
    - atr_ratio 0.3 → 30 (thị trường ngủ đông, kiệt sức → Fear nhẹ)
    - atr_ratio 0.7 → 45 (hơi thấp, gần neutral)
    - atr_ratio 1.0 → 55 (bình thường, slight greed - market đang hoạt động)
    - atr_ratio 1.5 → 45 (biến động cao - cảnh giác)
    - atr_ratio 2.5+ → 20 (panic, volatility spike)
    """
    if atr_ratio is None or atr_ratio <= 0:
        return 50.0
    
    if atr_ratio < 0.3:
        return 25.0 + (atr_ratio / 0.3) * 10.0   # 25 → 35 (cực thấp = Fear)
    elif atr_ratio < 0.7:
        return 35.0 + ((atr_ratio - 0.3) / 0.4) * 15.0   # 35 → 50 (thấp → neutral)
    elif atr_ratio < 1.0:
        return 50.0 + ((atr_ratio - 0.7) / 0.3) * 5.0   # 50 → 55 (peak greed nhẹ)
    elif atr_ratio < 1.5:
        return 55.0 - ((atr_ratio - 1.0) / 0.5) * 15.0   # 55 → 40
    elif atr_ratio < 2.5:
        return 40.0 - ((atr_ratio - 1.5) / 1.0) * 20.0   # 40 → 20
    else:
        return 20.0


def _score_momentum(pct_5d: Optional[float]) -> float:
    """Momentum 5-day return.
    -10% → 0, 0% → 50, +10% → 100 (more sensitive than cũ /5 → /10)
    """
    if pct_5d is None:
        return 50.0
    return max(0.0, min(100.0, 50.0 + (pct_5d / 10.0) * 50.0))


def _calc_fg_from_df(df_full) -> Dict[str, Any]:
    """Pure calculation from prepared DataFrame.
    PHASE 14C: subscore logic improved."""
    last = df_full.iloc[-1]
    close_now = float(last["close"])

    # ---- RSI ----
    rsi = _safe_float(last.get("rsi"))
    rsi_score = _score_rsi(rsi)

    # ---- MA200 distance ----
    ma200 = _safe_float(last.get("ma200"))
    if ma200 is None or ma200 <= 0:
        ma200 = _safe_float(last.get("ma50")) or close_now
    pct_above_ma = ((close_now - ma200) / ma200) * 100 if ma200 > 0 else 0
    ma_score = _score_ma200(pct_above_ma)

    # ---- Volume ratio (FIXED) ----
    vol_ratio = _safe_float(last.get("vol_ratio"))
    vol_score = _score_volume(vol_ratio)

    # ---- Volatility (FIXED - U-curve) ----
    recent_atr = df_full["close"].pct_change().rolling(14).std().iloc[-1] * 100
    avg_atr = df_full["close"].pct_change().rolling(60).std().iloc[-1] * 100
    atr_ratio = None
    if recent_atr and avg_atr and avg_atr > 0:
        atr_ratio = recent_atr / avg_atr
    vol_score_atr = _score_volatility(atr_ratio)

    # ---- Momentum 5D (more sensitive) ----
    pct_5d = None
    if len(df_full) >= 5:
        close_5d_ago = float(df_full["close"].iloc[-5])
        pct_5d = ((close_now - close_5d_ago) / close_5d_ago) * 100
    mom_score = _score_momentum(pct_5d)

    # ---- Weighted total ----
    score = (
        rsi_score * 0.30
        + ma_score * 0.25
        + vol_score * 0.20
        + vol_score_atr * 0.15
        + mom_score * 0.10
    )
    score = round(max(0, min(100, score)), 1)

    # ---- Label ----
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
            "volume": {"value": round(vol_ratio, 2) if vol_ratio else None, "score": round(vol_score, 1), "weight": 20, "label": "Vol/MA20"},
            "volatility": {"value": round(atr_ratio, 2) if atr_ratio else None, "score": round(vol_score_atr, 1), "weight": 15, "label": "Biến động"},
            "momentum": {"value": round(pct_5d, 2) if pct_5d is not None else None, "score": round(mom_score, 1), "weight": 10, "label": "Momentum 5D"},
        },
        "updated_at": datetime.now().isoformat(),
    }


# ============================================================
# SECTOR HEATMAP + STOCKS PER SECTOR (unchanged)
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
    pass


_CACHE = {"fg": None, "fg_at": 0, "sectors": None, "sectors_at": 0,
          "sector_stocks": {}, "sector_stocks_at": {}}
_CACHE_TTL = 300
_STOCK_CACHE_TTL = 180


async def compute_sector_heatmap() -> Dict[str, Any]:
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
                    continue
                except SystemExit as se:
                    raise _RateLimitStop()
                except Exception:
                    continue

            if pct_changes:
                avg_pct = sum(pct_changes) / len(pct_changes)
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
        }
    except Exception as e:
        logger.exception(f"Sector heatmap fail: {e}")
        return {"sectors": [], "error": str(e)}


async def _fetch_one_stock(ticker: str, start: str, end: str) -> Optional[Dict[str, Any]]:
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
        return None
    except SystemExit:
        raise _RateLimitStop()
    except Exception:
        return None


async def get_sector_stocks(sector_key: str) -> Dict[str, Any]:
    import time as _time

    if sector_key not in SECTOR_STOCKS:
        return {
            "sector": sector_key,
            "stocks": [],
            "error": f"Unknown sector: {sector_key}",
            "available": list(SECTOR_STOCKS.keys()),
        }

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

    try:
        for tk in tickers:
            await asyncio.sleep(0.35)
            res = await _fetch_one_stock(tk, start, end)
            if res:
                stocks.append(res)
    except _RateLimitStop:
        partial = True
    except Exception as e:
        logger.exception(f"[sector_stocks] {sector_key}: {e}")

    stocks.sort(key=lambda x: x["pct"], reverse=True)

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

    if len(stocks) >= max(3, len(tickers) // 2):
        _CACHE["sector_stocks"][sector_key] = result
        _CACHE["sector_stocks_at"][sector_key] = _time.time()

    return result


# Standalone test
if __name__ == "__main__":
    import json

    async def _test():
        print("=== FEAR & GREED ===")
        fg = await compute_fear_greed()
        print(json.dumps(fg, ensure_ascii=False, indent=2))

    asyncio.run(_test())
