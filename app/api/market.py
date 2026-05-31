"""
Market API router - Phase 7 + 8D + 8E
Endpoints:
- GET /api/market/fear-greed             → Fear & Greed Index (current)
- GET /api/market/fear-greed/history     → Historical snapshots (Phase 8D)
- GET /api/market/fear-greed/stats       → Aggregate stats (Phase 8D)
- GET /api/market/sectors                → Sector Heatmap
- GET /api/market/sectors/{key}/stocks   → Stocks in a sector (Phase 8E)
- GET /api/market/overview               → Combined
"""
from fastapi import APIRouter, HTTPException, Query
from loguru import logger

router = APIRouter(tags=["market"])


@router.get("/fear-greed")
async def get_fear_greed():
    """Fear & Greed Index. Side effect: persists snapshot to history."""
    from app.services.market import compute_fear_greed
    try:
        return await compute_fear_greed()
    except Exception as e:
        logger.exception(f"fear-greed error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.get("/fear-greed/history")
async def get_fear_greed_history(
    days: int = Query(30, ge=1, le=365, description="Số ngày lịch sử lấy về"),
):
    """Lịch sử Fear & Greed Index trong N ngày qua (oldest-first)."""
    try:
        from app.services import fg_history
        points = fg_history.get_history(days=days)
        return {"days": days, "count": len(points), "points": points}
    except Exception as e:
        logger.exception(f"fg history error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.get("/fear-greed/stats")
async def get_fear_greed_stats():
    """Tổng hợp thống kê F&G history."""
    try:
        from app.services import fg_history
        return fg_history.get_stats()
    except Exception as e:
        logger.exception(f"fg stats error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.get("/sectors")
async def get_sectors():
    """Sector Heatmap - % change by sector."""
    from app.services.market import compute_sector_heatmap
    try:
        return await compute_sector_heatmap()
    except Exception as e:
        logger.exception(f"sectors error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.get("/sectors/{sector_key:path}/stocks")
async def get_sector_stocks(sector_key: str):
    """Lấy tất cả mã trong 1 ngành (Phase 8E).
    
    sector_key dùng path param vì có space (vd 'Real Estate'), nên bật `:path`.
    Frontend phải encodeURIComponent trước khi gọi.
    """
    from app.services.market import get_sector_stocks as _get
    try:
        from urllib.parse import unquote
        key = unquote(sector_key)
        return await _get(key)
    except Exception as e:
        logger.exception(f"sector stocks error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.get("/overview")
async def get_market_overview():
    """Combined: Fear&Greed + Sectors."""
    from app.services.market import compute_fear_greed, compute_sector_heatmap
    try:
        fg = await compute_fear_greed()
        sectors = await compute_sector_heatmap()
        return {"fear_greed": fg, "sectors": sectors}
    except Exception as e:
        logger.exception(f"market overview error: {e}")
        raise HTTPException(500, f"Failed: {e}")
