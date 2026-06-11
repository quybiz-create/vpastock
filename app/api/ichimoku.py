"""
Phase 17A API: Ichimoku Cloud endpoints

- GET /api/ichimoku/symbol/{symbol} - lấy Ichimoku cho 1 mã
- GET /api/ichimoku/scan - scan universe tìm mã có signal tốt
"""
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from loguru import logger

router = APIRouter()


@router.get("/symbol/{symbol}")
async def get_ichimoku_symbol(symbol: str):
    """Lấy Ichimoku Cloud cho 1 symbol."""
    try:
        from app.services.ichimoku import get_ichimoku
        result = await get_ichimoku(symbol)
        if "error" in result:
            raise HTTPException(400, result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[ichimoku API] symbol fail: {e}")
        raise HTTPException(500, str(e))


@router.get("/scan")
async def scan_ichimoku_endpoint(
    signal: Optional[str] = Query(None, pattern="^(strong_buy|buy|neutral|sell|strong_sell)$"),
    force: bool = Query(False),
):
    """Scan toàn universe theo Ichimoku, optional filter theo signal level."""
    try:
        from app.services.ichimoku import scan_ichimoku
        result = await scan_ichimoku(filter_signal=signal, force_refresh=force)
        return result
    except Exception as e:
        logger.exception(f"[ichimoku API] scan fail: {e}")
        raise HTTPException(500, str(e))
