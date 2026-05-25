"""
API endpoints cho stock detail.
Đây là API quan trọng nhất - phục vụ trang Chi tiết CP.
"""
import math
import pandas as pd
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

# ============================================================
# RSI COMBO INDICATOR (Phase 3 Day 4)
# ============================================================
@router.get("/{symbol}/rsi-combo")
async def get_rsi_combo(
    symbol: str,
    days: int = Query(default=365, ge=60, le=1825),
):
    """
    RSI Combo System: 6 loai signals.
    """
    from app.services.rsi_combo import calculate_rsi_combo
    
    try:
        # Reuse Phase 1 vnstock client (handles fallback + cache)
        from datetime import datetime, timedelta
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        df = await vnstock_client.get_history(symbol.upper(), start=start_date, end=end_date, interval="1D")
        
        if df is None or df.empty:
            raise HTTPException(404, f"No data for {symbol}")
        
        # Build clean DataFrame with explicit 'time' column from index
        df_clean = pd.DataFrame({
            "time": pd.to_datetime(df.index).astype("int64") // 1_000_000,
            "open": df["open"].values,
            "high": df["high"].values,
            "low": df["low"].values,
            "close": df["close"].values,
        })
        
        signals = calculate_rsi_combo(df_clean)
        
        return {
            "symbol": symbol.upper(),
            "params": {
                "rsi_length": 14,
                "rsi_overbought": 70,
                "rsi_oversold": 30,
                "fib_level": 0.333,
                "combo_lookback": 10,
            },
            "signals": signals,
            "counts": {k: len(v) for k, v in signals.items()},
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"RSI Combo error for {symbol}: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Failed to calculate: {e}")
#---

# ============================================================
# EMA CROSS + SUPERTREND (Phase 3 Day 5)
# ============================================================
@router.get("/{symbol}/ema-supertrend")
async def get_ema_supertrend(
    symbol: str,
    days: int = Query(default=365, ge=60, le=1825),
    ema_fast: int = Query(default=20, ge=5, le=100),
    ema_slow: int = Query(default=40, ge=10, le=200),
    st_period: int = Query(default=5, ge=2, le=30),
    st_mult: float = Query(default=2.0, ge=0.5, le=10.0),
):
    """
    EMA Cross + SuperTrend - convert tu AmiBroker AFL.
    """
    from app.services.ema_supertrend import calculate_ema_cross, calculate_supertrend
    
    try:
        from datetime import timedelta
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        df = await vnstock_client.get_history(
            symbol.upper(), start=start_date, end=end_date, interval="1D"
        )
        
        if df is None or df.empty:
            raise HTTPException(404, f"No data for {symbol}")
        
        # Build clean DataFrame
        df_clean = pd.DataFrame({
            "time": pd.to_datetime(df.index).astype("int64") // 1_000_000,
            "open": df["open"].values,
            "high": df["high"].values,
            "low": df["low"].values,
            "close": df["close"].values,
        })
        
        ema_result = calculate_ema_cross(df_clean, fast=ema_fast, slow=ema_slow)
        st_result = calculate_supertrend(df_clean, period=st_period, multiplier=st_mult)
        
        return {
            "symbol": symbol.upper(),
            "ema": ema_result,
            "supertrend": st_result,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"EMA/SuperTrend error for {symbol}: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Failed to calculate: {e}")
   #---------------------------
# ============================================================
# PIVOT FINDER - AmiBroker Trading System (Phase 3 Day 6)
# ============================================================
@router.get("/{symbol}/pivots")
async def get_pivots(
    symbol: str,
    days: int = Query(default=365, ge=60, le=1825),
    n_bars: int = Query(default=12, ge=3, le=50),
    farback: int = Query(default=100, ge=20, le=500),
):
    """
    Pivot High/Low (Buy/Sell signals) chuan AmiBroker.
    """
    from app.services.pivot_finder import calculate_pivots
    
    try:
        from datetime import timedelta
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        df = await vnstock_client.get_history(
            symbol.upper(), start=start_date, end=end_date, interval="1D"
        )
        
        if df is None or df.empty:
            raise HTTPException(404, f"No data for {symbol}")
        
        df_clean = pd.DataFrame({
            "time": pd.to_datetime(df.index).astype("int64") // 1_000_000,
            "open": df["open"].values,
            "high": df["high"].values,
            "low": df["low"].values,
            "close": df["close"].values,
        })
        
        result = calculate_pivots(df_clean, n_bars=n_bars, farback=farback)
        result["symbol"] = symbol.upper()
        return result
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Pivot error for {symbol}: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Failed: {e}")

#---------------------------------------------------------------------------------
# ============================================================
# AI DEEP ANALYSIS - Phase 4 (Streaming SSE)
# ============================================================
@router.get("/{symbol}/ai-deep")
async def ai_deep_analysis(symbol: str):
    """
    AI Claude phan tich chuyen sau tong hop 12 features.
    Stream response qua Server-Sent Events.
    """
    from fastapi.responses import StreamingResponse
    from app.services.ai_deep import analyze_stream
    from datetime import timedelta
    
    symbol = symbol.upper()
    
    # === Step 1: Collect data from all features ===
    data = {}
    
    try:
        # Common date range
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        
        # 1. Indicators (last + minimal series)
        try:
            df = await vnstock_client.get_history(symbol, start=start_date, end=end_date, interval="1D")
            if df is not None and not df.empty:
                from app.core.indicators import compute_all
                df_ind = compute_all(df)
                if len(df_ind) > 0:
                    last_row = df_ind.iloc[-1]
                    data["indicators"] = {
                        "last": {
                            "price": float(last_row.get("close", 0)),
                            "ma20": _safe_float(last_row.get("ma20")),
                            "ma50": _safe_float(last_row.get("ma50")),
                            "ma200": _safe_float(last_row.get("ma200")),
                            "rsi": _safe_float(last_row.get("rsi")),
                            "macd": _safe_float(last_row.get("macd")),
                            "macd_signal": _safe_float(last_row.get("macd_signal")),
                            "mfi": _safe_float(last_row.get("mfi")),
                            "adx": _safe_float(last_row.get("adx")),
                            "plus_di": _safe_float(last_row.get("plus_di")),
                            "minus_di": _safe_float(last_row.get("minus_di")),
                            "bb_upper": _safe_float(last_row.get("bb_upper")),
                            "bb_middle": _safe_float(last_row.get("bb_middle")),
                            "bb_lower": _safe_float(last_row.get("bb_lower")),
                            "vol_ratio": _safe_float(last_row.get("vol_ratio")),
                            "vpa": last_row.get("vpa", "Normal"),
                        }
                    }
        except Exception as e:
            logger.warning(f"[AI DEEP] indicators fail: {e}")
        
        # 2. Build df_clean for indicators
        if df is not None and not df.empty:
            df_clean = pd.DataFrame({
                "time": pd.to_datetime(df.index).astype("int64") // 1_000_000,
                "open": df["open"].values,
                "high": df["high"].values,
                "low": df["low"].values,
                "close": df["close"].values,
            })
            
            # 3. RSI Combo
            try:
                from app.services.rsi_combo import calculate_rsi_combo
                rsi_result = calculate_rsi_combo(df_clean)
                data["rsi_combo"] = {"counts": {k: len(v) for k, v in rsi_result.items() if isinstance(v, list)}}
            except Exception as e:
                logger.warning(f"[AI DEEP] rsi_combo fail: {e}")
            
            # 4. EMA + SuperTrend
            try:
                from app.services.ema_supertrend import calculate_ema_cross, calculate_supertrend
                ema_r = calculate_ema_cross(df_clean)
                st_r = calculate_supertrend(df_clean)
                data["ema_supertrend"] = {
                    "ema": {"counts": ema_r.get("counts", {})},
                    "supertrend": {"counts": st_r.get("counts", {})},
                }
            except Exception as e:
                logger.warning(f"[AI DEEP] ema_st fail: {e}")
            
            # 5. Pivot Finder
            try:
                from app.services.pivot_finder import calculate_pivots
                pivot_r = calculate_pivots(df_clean)
                data["pivots"] = {
                    "last_signal": pivot_r.get("last_signal"),
                    "counts": pivot_r.get("counts", {}),
                }
            except Exception as e:
                logger.warning(f"[AI DEEP] pivot fail: {e}")
    
    except Exception as e:
        logger.error(f"[AI DEEP] Data collection fail for {symbol}: {e}")
        raise HTTPException(500, f"Data collection failed: {e}")
    
    # === Step 2: Stream AI response ===
    async def event_generator():
        try:
            async for chunk in analyze_stream(symbol, data):
                # SSE format: data: <text>\n\n
                # Escape newlines in chunk to keep SSE valid
                safe = chunk.replace("\n", "\\n")
                yield f"data: {safe}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"[AI DEEP] Stream error: {e}")
            yield f"data: \\n\\n⚠️ Loi: {str(e)}\n\n"
            yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Connection": "keep-alive",
        },
    )