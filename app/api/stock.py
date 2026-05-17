"""
API endpoints cho stock detail.
Đây là API quan trọng nhất - phục vụ trang Chi tiết CP.
"""
import math
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from app.data.vnstock_client import vnstock_client
from app.core.indicators import compute_all
from app.services.ai_analyzer import ai_analyzer


router = APIRouter()


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


@router.get("/{symbol}/history")
async def get_history(
    symbol: str,
    days: int = Query(default=365, ge=10, le=1825),
    interval: str = Query(default="1D"),
):
    try:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        df = await vnstock_client.get_history(symbol, start=start, end=end, interval=interval)
        if df.empty:
            raise HTTPException(404, f"Khong co du lieu cho {symbol}")

        records = []
        for idx, row in df.iterrows():
            records.append({
                "time": int(idx.timestamp() * 1000),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
            })

        return {
            "symbol": symbol.upper(),
            "interval": interval,
            "count": len(records),
            "data": records,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"get_history loi cho {symbol}")
        raise HTTPException(500, f"Loi: {str(e)}")


@router.get("/{symbol}/indicators")
async def get_indicators(
    symbol: str,
    days: int = Query(default=365, ge=60, le=1825),
):
    try:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        df = await vnstock_client.get_history(symbol, start=start, end=end)
        if df.empty:
            raise HTTPException(404, f"Khong co du lieu cho {symbol}")

        df_full = compute_all(df)
        last = df_full.iloc[-1]

        last_summary = {
            "price": float(last["close"]),
            "ma20": _safe_float(last.get("ma20")),
            "ma50": _safe_float(last.get("ma50")),
            "ma200": _safe_float(last.get("ma200")),
            "rsi": _safe_float(last.get("rsi")),
            "macd": _safe_float(last.get("macd")),
            "macd_signal": _safe_float(last.get("signal")),
            "mfi": _safe_float(last.get("mfi")),
            "bb_upper": _safe_float(last.get("bb_upper")),
            "bb_middle": _safe_float(last.get("bb_middle")),
            "bb_lower": _safe_float(last.get("bb_lower")),
            "adx": _safe_float(last.get("adx")),
            "plus_di": _safe_float(last.get("plus_di")),
            "minus_di": _safe_float(last.get("minus_di")),
            "tenkan": _safe_float(last.get("tenkan")),
            "kijun": _safe_float(last.get("kijun")),
            "vol_ratio": _safe_float(last.get("vol_ratio")),
            "vpa": str(last.get("vpa", "Normal")),
        }

        series = []
        for idx, row in df_full.iterrows():
            series.append({
                "time": int(idx.timestamp() * 1000),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "ma20": _safe_float(row.get("ma20")),
                "ma50": _safe_float(row.get("ma50")),
                "rsi": _safe_float(row.get("rsi")),
                "vpa": str(row.get("vpa", "Normal")),
            })

        return {
            "symbol": symbol.upper(),
            "last": last_summary,
            "series": series,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"get_indicators loi cho {symbol}")
        raise HTTPException(500, f"Loi: {str(e)}")


@router.get("/{symbol}/ai")
async def get_ai_analysis(symbol: str):
    try:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

        df = await vnstock_client.get_history(symbol, start=start, end=end)
        if df.empty:
            raise HTTPException(404, f"Khong co du lieu cho {symbol}")

        df_full = compute_all(df)
        return await ai_analyzer.analyze(symbol.upper(), df_full)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"get_ai_analysis loi cho {symbol}")
        raise HTTPException(500, f"Loi AI: {str(e)}")


@router.get("/{symbol}/overview")
async def get_overview(symbol: str):
    try:
        return await vnstock_client.get_company_overview(symbol)
    except Exception as e:
        logger.exception(f"get_overview loi cho {symbol}")
        raise HTTPException(500, f"Loi: {str(e)}")


@router.get("/{symbol}/financial")
async def get_financial(symbol: str):
    try:
        return await vnstock_client.get_financial_ratios(symbol)
    except Exception as e:
        logger.exception(f"get_financial loi cho {symbol}")
        raise HTTPException(500, f"Loi: {str(e)}")