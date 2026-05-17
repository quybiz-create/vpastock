"""
API endpoints cho screener / bộ lọc.
Phase 2 - skeleton.
"""
from typing import Literal
from fastapi import APIRouter, Query


router = APIRouter()


FilterPreset = Literal[
    "above_ma20", "above_ma50", "breaking_ma20",
    "squeeze", "vpa_setup", "strong_trend"
]


@router.get("/filter")
async def filter_stocks(
    preset: FilterPreset = Query(default="above_ma20"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    Lọc CP theo preset.
    Phase 2: sẽ scan toàn bộ HoSE+HNX với indicators module đã có.
    """
    return {
        "preset": preset,
        "status": "not_implemented",
        "message": "Sẽ implement scanner async ở Phase 2, dùng app.core.indicators",
    }
