"""
Wyckoff Phase Detection API - Phase 9A + 9B + 9C + 9D

Endpoints:
- GET  /api/wyckoff/{symbol}?period=200&tf=D      → single TF
- GET  /api/wyckoff/{symbol}/multi?period=200     → multi-TF
- POST /api/wyckoff/{symbol}/advisor              → AI advisor (9C)
- POST /api/wyckoff/scan/start                    → start scan job (9D)
- GET  /api/wyckoff/scan/status/{job_id}          → poll progress (9D)
- GET  /api/wyckoff/scan/results/{job_id}         → get results (9D)
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Path, Query
from loguru import logger

router = APIRouter(tags=["wyckoff"])


def _resample_bars(bars: List[Dict[str, Any]], freq: str) -> List[Dict[str, Any]]:
    if not bars:
        return []
    try:
        import pandas as pd
        df = pd.DataFrame(bars)
        df["dt"] = pd.to_datetime(df["time"])
        df = df.set_index("dt")
        rule = "W-FRI" if freq == "W" else "ME"
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        rs = df.resample(rule).agg(agg).dropna()
        out = []
        for idx, row in rs.iterrows():
            out.append({
                "time": idx.strftime("%Y-%m-%d"),
                "open": float(row["open"]), "high": float(row["high"]),
                "low": float(row["low"]), "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
        return out
    except Exception as e:
        logger.warning(f"[wyckoff] resample {freq} fail: {e}")
        return []


async def _load_bars(symbol: str, days_back: int) -> List[Dict[str, Any]]:
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
            "open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"]),
            "volume": float(row.get("volume", 0) or 0),
        })
    return bars


@router.get("/{symbol}")
async def get_wyckoff(
    symbol: str = Path(..., min_length=1, max_length=10),
    period: int = Query(200, ge=50, le=400),
    tf: str = Query("D"),
):
    """Phân tích Wyckoff trên 1 timeframe."""
    from app.services.wyckoff import analyze_wyckoff
    symbol = symbol.upper().strip()
    tf = tf.upper()
    if tf not in ("D", "W", "M"):
        raise HTTPException(400, "tf must be D, W, or M")
    try:
        days_back = {"D": max(period * 2, 300), "W": period * 8, "M": period * 32}[tf]
        bars = await _load_bars(symbol, days_back)
        if not bars:
            raise HTTPException(404, f"Không lấy được dữ liệu cho {symbol}")
        if len(bars) < 50:
            raise HTTPException(400, "Không đủ dữ liệu (cần ít nhất 50 bars)")
        if tf == "W":
            bars = _resample_bars(bars, "W")
        elif tf == "M":
            bars = _resample_bars(bars, "M")
        if len(bars) < 50:
            raise HTTPException(400, f"Không đủ dữ liệu TF {tf} ({len(bars)} bars)")
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
    """Multi-timeframe Wyckoff + alignment."""
    from app.services.wyckoff import analyze_wyckoff
    symbol = symbol.upper().strip()
    try:
        days_back = max(period * 32, 1500)
        bars_d = await _load_bars(symbol, days_back)
        if not bars_d or len(bars_d) < 50:
            raise HTTPException(404, f"Không đủ dữ liệu cho {symbol}")
        result: Dict[str, Any] = {"symbol": symbol}
        try:
            r_d = analyze_wyckoff(bars_d, period=period)
            r_d["bars_analyzed"] = len(bars_d[-period:])
            result["daily"] = r_d
        except Exception as e:
            result["daily"] = {"error": str(e)}
        try:
            bars_w = _resample_bars(bars_d, "W")
            if len(bars_w) >= 30:
                r_w = analyze_wyckoff(bars_w, period=min(period, len(bars_w)))
                r_w["bars_analyzed"] = len(bars_w)
                result["weekly"] = r_w
            else:
                result["weekly"] = {"error": f"Chỉ có {len(bars_w)} bars"}
        except Exception as e:
            result["weekly"] = {"error": str(e)}
        try:
            bars_m = _resample_bars(bars_d, "M")
            if len(bars_m) >= 24:
                r_m = analyze_wyckoff(bars_m, period=min(period, len(bars_m)))
                r_m["bars_analyzed"] = len(bars_m)
                result["monthly"] = r_m
            else:
                result["monthly"] = {"error": f"Chỉ có {len(bars_m)} bars"}
        except Exception as e:
            result["monthly"] = {"error": str(e)}
        setups = []
        for key in ("daily", "weekly", "monthly"):
            td = result.get(key, {})
            if "setup" in td and td.get("setup") != "none":
                setups.append((key, td["setup"], td.get("phase", "?")))
        alignment = "mixed"
        if len(setups) >= 2:
            unique_setups = set(s[1] for s in setups)
            if len(unique_setups) == 1:
                alignment = next(iter(unique_setups))
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


@router.post("/{symbol}/advisor")
async def get_wyckoff_advisor(
    symbol: str = Path(..., min_length=1, max_length=10),
    refresh: bool = Query(False),
):
    """🤖 AI Trading Advisor (Phase 9C)."""
    from app.services.wyckoff_advisor import get_ai_advisor
    try:
        return await get_ai_advisor(symbol, force_refresh=refresh)
    except Exception as e:
        logger.exception(f"wyckoff advisor {symbol} error: {e}")
        raise HTTPException(500, f"Failed: {e}")


# ============================================================
# Phase 9D: Scanner endpoints
# ============================================================
@router.post("/scan/start")
async def start_wyckoff_scan(
    symbols: Optional[str] = Query(None, description="CSV symbols (vd 'VCB,VIC'), bỏ trống = top 200"),
):
    """🎯 Phase 9D: Khởi tạo scan job cho top 200 mã (hoặc list tự chọn).
    
    Trả về job_id để frontend poll status.
    """
    from app.services.wyckoff_scanner import start_scan, TOP_200_SYMBOLS
    try:
        syms = None
        if symbols:
            syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
            if not syms:
                syms = None
        job_id = start_scan(syms)
        return {
            "job_id": job_id,
            "status": "queued",
            "total": len(syms) if syms else len(TOP_200_SYMBOLS),
            "message": "Scan đã bắt đầu. Poll /scan/status/{job_id} để xem tiến độ.",
        }
    except Exception as e:
        logger.exception(f"wyckoff scan start error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.get("/scan/status/{job_id}")
async def get_wyckoff_scan_status(job_id: str = Path(..., min_length=4, max_length=40)):
    """🎯 Phase 9D: Poll progress của scan job."""
    from app.services.wyckoff_scanner import get_job_status
    status = get_job_status(job_id)
    if not status:
        raise HTTPException(404, f"Job {job_id} không tồn tại hoặc đã hết hạn")
    return status


@router.get("/scan/results/{job_id}")
async def get_wyckoff_scan_results(job_id: str = Path(..., min_length=4, max_length=40)):
    """🎯 Phase 9D: Lấy kết quả scan khi job done."""
    from app.services.wyckoff_scanner import get_job_results
    results = get_job_results(job_id)
    if not results:
        raise HTTPException(404, f"Job {job_id} không tồn tại")
    return results
