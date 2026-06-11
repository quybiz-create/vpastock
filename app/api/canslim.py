"""
Phase 16A API: CANSLIM Scanner endpoint
"""
from fastapi import APIRouter, Query, HTTPException
from loguru import logger

router = APIRouter()


@router.get("/scan")
async def scan_canslim_endpoint(
    force: bool = Query(False, description="Bỏ qua cache, scan lại"),
    min_score: int = Query(0, ge=0, le=7, description="Filter mã có score ≥ N"),
):
    """Scan toàn bộ universe theo 7 tiêu chí CANSLIM của William O'Neil.
    
    Returns: { matches: [...], summary: {...} }
    """
    try:
        from app.services.canslim_scanner import scan_canslim
        
        result = await scan_canslim(force_refresh=force)
        
        # Filter by min_score
        if min_score > 0:
            result["matches"] = [m for m in result["matches"] if m["score"] >= min_score]
        
        return result
    except Exception as e:
        logger.exception(f"[canslim API] scan fail: {e}")
        raise HTTPException(500, str(e))


@router.get("/symbol/{symbol}")
async def check_one_symbol(symbol: str):
    """Check CANSLIM cho 1 mã cụ thể (không cần scan toàn bộ)."""
    try:
        import httpx
        from app.services.canslim_scanner import _compute_one_symbol, get_market_context
        
        symbol = symbol.upper().strip()
        market_ctx = await get_market_context()
        
        async with httpx.AsyncClient() as client:
            result = await _compute_one_symbol(symbol, market_ctx, client)
        
        if not result:
            raise HTTPException(404, f"Không phân tích được {symbol}")
        
        return {"symbol": symbol, "market": market_ctx, **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[canslim API] symbol fail: {e}")
        raise HTTPException(500, str(e))
