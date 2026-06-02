"""
Wyckoff Phase Detection API - Phase 9A

Endpoint:
- GET /api/wyckoff/{symbol}?period=200

Trả về phân tích Wyckoff cho symbol với các phase A/B/C/D/E
và events SC/BC/AR/Spring/UTAD trên chart.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Path, Query
from loguru import logger

router = APIRouter(tags=["wyckoff"])


@router.get("/{symbol}")
async def get_wyckoff(
    symbol: str = Path(..., min_length=1, max_length=10),
    period: int = Query(200, ge=50, le=400, description="Số bars phân tích (50-400)"),
):
    """Phân tích Wyckoff Phase cho symbol.

    Args:
        symbol: Mã CK (VD: VIC, HPG)
        period: Số bars phân tích (default 200 ~10 tháng)

    Returns:
        {
            "symbol": "VIC",
            "setup": "accumulation" | "distribution" | "none",
            "phase": "A" | "B" | "C" | "D" | "E" | "none",
            "confidence": 0.0..1.0,
            "trading_range": {high, low, mid, start_idx, end_idx, bars_count, range_pct},
            "events": [{index, time, price, type, desc, confidence}, ...],
            "suggestion": "...",
            "description": "...",
            "pre_trend": "up" | "down" | "sideway"
        }
    """
    from app.data.vnstock_client import vnstock_client
    from app.services.wyckoff import analyze_wyckoff

    symbol = symbol.upper().strip()
    try:
        # Lấy dữ liệu lịch sử
        # period*2 ngày để chắc chắn đủ trading bars sau khi loại weekend/holiday
        days_back = max(period * 2, 300)
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        df = await vnstock_client.get_history(symbol, start=start, end=end)
        if df is None or df.empty:
            raise HTTPException(404, f"Không lấy được dữ liệu cho {symbol}")

        df = df[~df.index.duplicated(keep="last")].sort_index()
        if len(df) < 50:
            raise HTTPException(400, "Không đủ dữ liệu (cần ít nhất 50 bars)")

        # Convert DataFrame → list of dicts (giữ time index)
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

        result = analyze_wyckoff(bars, period=period)
        result["symbol"] = symbol
        result["bars_analyzed"] = len(bars[-period:])
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"wyckoff {symbol} error: {e}")
        raise HTTPException(500, f"Failed: {e}")
