"""
Phase 8C: News + Sentiment API

Endpoints:
- GET /api/news/{symbol}              → 10 tin mới nhất + keyword sentiment
- POST /api/news/{symbol}/analyze     → AI Claude phân tích tổng hợp (on-demand)
"""
from fastapi import APIRouter, HTTPException, Path
from loguru import logger

router = APIRouter(tags=["news"])


@router.get("/{symbol}")
async def get_news(symbol: str = Path(..., min_length=1, max_length=10)):
    """Lấy 10 tin tức mới nhất kèm sentiment keyword cho symbol."""
    from app.services.news_sentiment import get_news as _get
    try:
        return await _get(symbol)
    except Exception as e:
        logger.exception(f"news GET {symbol} error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.post("/{symbol}/analyze")
async def analyze_news(symbol: str = Path(..., min_length=1, max_length=10)):
    """AI tổng hợp tin tức thành 1 đoạn đánh giá. Cache 1 giờ."""
    from app.services.news_sentiment import analyze_news_deep
    try:
        return await analyze_news_deep(symbol)
    except Exception as e:
        logger.exception(f"news AI {symbol} error: {e}")
        raise HTTPException(500, f"Failed: {e}")
