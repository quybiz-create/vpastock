"""
Wyckoff Phase Detection API - Phase 9A + 9B

Endpoints:
- GET /api/wyckoff/{symbol}?period=200&tf=D
- GET /api/wyckoff/{symbol}/multi?period=200    (Phase 9B: D + W + M)
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Path, Query
from loguru import logger

router = APIRouter(tags=["wyckoff"])


def _resample_bars(bars: List[Dict[str, Any]], freq: str) -> List[Dict[str, Any]]:
    """Resample daily bars to weekly/monthly OHLCV.

    freq: 'W' (weekly Monday-Sunday) hoặc 'M' (monthly).
    """
    if not bars:
        return []
    
    try:
        import pandas as pd
        df = pd.DataFrame(bars)
        # Time → datetime
        df["dt"] = pd.to_datetime(df["time"])
        df = df.set_index("dt")
        rule = "W-FRI" if freq == "W" else "ME"   # week ending Friday, month end
        agg = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
        rs = df.resample(rule).agg(agg).dropna()
        out = []
        for idx, row in rs.iterrows():
            out.append({
                "time": idx.strftime("%Y-%m-%d"),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
        return out
    except Exception as e:
        logger.warning(f"[wyckoff] resample {freq} fail: {e}")
        return []


async def _load_bars(symbol: str, days_back: int) -> List[Dict[str, Any]]:
    """Helper load bars từ vnstock."""
    from app.data.vnstock_client import vnstock_client
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    df = await vnstock_client.get_history(symbol, start=start, end=end)
    if df is None or df.empty:
        return []
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
    return bars


@router.get("/{symbol}")
async def get_wyckoff(
    symbol: str = Path(..., min_length=1, max_length=10),
    period: int = Query(200, ge=50, le=400, description="Số bars phân tích"),
    tf: str = Query("D", description="Timeframe: D (daily), W (weekly), M (monthly)"),
):
    """Phân tích Wyckoff cho symbol trên 1 timeframe.

    Phase 9B: hỗ trợ thêm event detection ST, LPS/LPSY, SOS/SOW, Spring Test.
    """
    from app.services.wyckoff import analyze_wyckoff
    
    symbol = symbol.upper().strip()
    tf = tf.upper()
    if tf not in ("D", "W", "M"):
        raise HTTPException(400, "tf must be D, W, or M")
    
    try:
        # Lượng data cần load tùy timeframe
        # D: period bars cần ~period*2 ngày dương lịch
        # W: cần ~period*7 ngày (cho weekly)
        # M: cần ~period*30 ngày (cho monthly)
        days_back = {"D": max(period * 2, 300), "W": period * 8, "M": period * 32}[tf]
        bars = await _load_bars(symbol, days_back)
        if not bars:
            raise HTTPException(404, f"Không lấy được dữ liệu cho {symbol}")
        if len(bars) < 50:
            raise HTTPException(400, "Không đủ dữ liệu (cần ít nhất 50 bars)")
        
        # Resample nếu cần
        if tf == "W":
            bars = _resample_bars(bars, "W")
        elif tf == "M":
            bars = _resample_bars(bars, "M")
        
        if len(bars) < 50:
            raise HTTPException(
                400,
                f"Không đủ dữ liệu cho timeframe {tf} (chỉ có {len(bars)} bars sau resample)",
            )
        
        result = analyze_wyckoff(bars, period=period)
        result["symbol"] = symbol
        result["timeframe"] = tf
        result["bars_analyzed"] = len(bars[-period:])
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"wyckoff {symbol} {tf} error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.get("/{symbol}/multi")
async def get_wyckoff_multi(
    symbol: str = Path(..., min_length=1, max_length=10),
    period: int = Query(200, ge=50, le=400),
):
    """Phase 9B: Phân tích Wyckoff trên 3 timeframe D + W + M.

    Trả về dict với 3 key 'daily', 'weekly', 'monthly'.
    Giúp xác định alignment giữa các timeframe (TF lớn lead TF nhỏ).
    """
    from app.services.wyckoff import analyze_wyckoff
    
    symbol = symbol.upper().strip()
    
    try:
        # Load 1 lần data lớn nhất rồi resample cho 3 TF
        days_back = max(period * 32, 1500)   # đủ cho monthly
        bars_d = await _load_bars(symbol, days_back)
        if not bars_d or len(bars_d) < 50:
            raise HTTPException(404, f"Không đủ dữ liệu cho {symbol}")
        
        result: Dict[str, Any] = {"symbol": symbol}
        
        # Daily
        try:
            r_d = analyze_wyckoff(bars_d, period=period)
            r_d["bars_analyzed"] = len(bars_d[-period:])
            result["daily"] = r_d
        except Exception as e:
            result["daily"] = {"error": str(e)}
        
        # Weekly
        try:
            bars_w = _resample_bars(bars_d, "W")
            if len(bars_w) >= 30:
                r_w = analyze_wyckoff(bars_w, period=min(period, len(bars_w)))
                r_w["bars_analyzed"] = len(bars_w)
                result["weekly"] = r_w
            else:
                result["weekly"] = {"error": f"Chỉ có {len(bars_w)} bars weekly"}
        except Exception as e:
            result["weekly"] = {"error": str(e)}
        
        # Monthly
        try:
            bars_m = _resample_bars(bars_d, "M")
            if len(bars_m) >= 24:
                r_m = analyze_wyckoff(bars_m, period=min(period, len(bars_m)))
                r_m["bars_analyzed"] = len(bars_m)
                result["monthly"] = r_m
            else:
                result["monthly"] = {"error": f"Chỉ có {len(bars_m)} bars monthly"}
        except Exception as e:
            result["monthly"] = {"error": str(e)}
        
        # Alignment summary
        setups = []
        for key in ("daily", "weekly", "monthly"):
            tf_data = result.get(key, {})
            if "setup" in tf_data and tf_data.get("setup") != "none":
                setups.append((key, tf_data["setup"], tf_data.get("phase", "?")))
        
        alignment = "mixed"
        if len(setups) >= 2:
            unique_setups = set(s[1] for s in setups)
            if len(unique_setups) == 1:
                alignment = next(iter(unique_setups))  # accumulation/distribution
        
        result["alignment"] = {
            "summary": alignment,
            "tf_setups": [{"tf": s[0], "setup": s[1], "phase": s[2]} for s in setups],
            "note": (
                "✅ Cả 3 TF đồng thuận — tín hiệu mạnh"
                if len(setups) == 3 and alignment != "mixed"
                else "⚠️ Các TF không đồng thuận — cần phân tích kỹ"
                if alignment == "mixed"
                else "🟡 Có 2 TF đồng thuận"
            ),
        }
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"wyckoff multi {symbol} error: {e}")
        raise HTTPException(500, f"Failed: {e}")
