"""
Market API router - Phase 7
Endpoints:
- GET /api/market/fear-greed  → Fear & Greed Index
- GET /api/market/sectors     → Sector Heatmap
- GET /api/market/overview    → Both combined
"""
from fastapi import APIRouter, HTTPException
from loguru import logger

router = APIRouter(tags=["market"])


@router.get("/fear-greed")
async def get_fear_greed():
    """Fear & Greed Index computed from VNINDEX indicators."""
    from app.services.market import compute_fear_greed
    try:
        return await compute_fear_greed()
    except Exception as e:
        logger.exception(f"fear-greed error: {e}")
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


@router.get("/overview")
async def get_market_overview():
    """Combined: Fear&Greed + Sectors."""
    from app.services.market import compute_fear_greed, compute_sector_heatmap
    try:
        fg = await compute_fear_greed()
        sectors = await compute_sector_heatmap()
        return {
            "fear_greed": fg,
            "sectors": sectors,
        }
    except Exception as e:
        logger.exception(f"market overview error: {e}")
        raise HTTPException(500, f"Failed: {e}")
