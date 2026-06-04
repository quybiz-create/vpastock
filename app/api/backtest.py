"""
Wyckoff Backtest API - Phase 13

Endpoints:
- POST /api/backtest/run                     → chạy backtest 1 mã 1 strategy
- POST /api/backtest/compare                 → chạy cả 3 strategies cho 1 mã (so sánh)
- GET  /api/backtest/strategies              → list các strategy có sẵn
"""
from fastapi import APIRouter, HTTPException, Query, Path
from pydantic import BaseModel, Field
from typing import Optional
from loguru import logger
import asyncio

router = APIRouter(tags=["backtest"])


class BacktestRunReq(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)
    strategy: str = Field("phase_d", description="classic / phase_d / setup_conf")
    period_years: int = Field(2, ge=1, le=5)
    refresh: bool = False


@router.get("/strategies")
async def get_strategies():
    """List các strategy có sẵn (cho dropdown UI)."""
    from app.services.backtest import get_strategy_info
    return {"strategies": get_strategy_info()}


@router.post("/run")
async def run_backtest_endpoint(req: BacktestRunReq):
    """Chạy backtest 1 mã 1 strategy."""
    from app.services.backtest import run_backtest
    try:
        result = await run_backtest(req.symbol, req.strategy, req.period_years, req.refresh)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception(f"backtest run {req.symbol} error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.post("/compare")
async def compare_strategies(
    symbol: str = Query(..., min_length=1, max_length=10),
    period_years: int = Query(2, ge=1, le=5),
    refresh: bool = Query(False),
):
    """Chạy cả 3 strategies song song và so sánh."""
    from app.services.backtest import run_backtest
    try:
        # Chạy song song 3 strategies
        results = await asyncio.gather(
            run_backtest(symbol, "classic", period_years, refresh),
            run_backtest(symbol, "phase_d", period_years, refresh),
            run_backtest(symbol, "setup_conf", period_years, refresh),
            return_exceptions=True,
        )
        
        # Format
        strategies_results = []
        for strategy, r in zip(["classic", "phase_d", "setup_conf"], results):
            if isinstance(r, Exception):
                strategies_results.append({
                    "strategy": strategy,
                    "error": str(r)[:200],
                })
            else:
                strategies_results.append({
                    "strategy": strategy,
                    "summary": r.get("summary"),
                    "error": r.get("error"),
                })
        
        return {
            "symbol": symbol,
            "period_years": period_years,
            "results": strategies_results,
        }
    except Exception as e:
        logger.exception(f"backtest compare {symbol} error: {e}")
        raise HTTPException(500, f"Failed: {e}")
