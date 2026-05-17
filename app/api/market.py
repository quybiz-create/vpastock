"""
API endpoints cho thị trường tổng thể.
Phase 2 - hiện tại chỉ skeleton để app chạy được.
"""
from fastapi import APIRouter


router = APIRouter()


@router.get("/breadth")
async def get_breadth():
    """Market breadth - sẽ port từ QuyStock ở Phase 2."""
    return {
        "status": "not_implemented",
        "message": "Sẽ port từ QuyStock Pro Tab MARKET ở Phase 2",
    }


@router.get("/fear-greed")
async def get_fear_greed():
    """Fear & Greed Index - Phase 2."""
    return {
        "value": 68,
        "label": "GREED",
        "status": "mock_data",
    }


@router.get("/heatmap")
async def get_heatmap():
    """Sector heatmap - Phase 2."""
    return {
        "status": "not_implemented",
        "message": "Sẽ implement với treemap ở Phase 2",
    }
