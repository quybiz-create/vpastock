"""
API endpoints cho screener / bo loc CP.
"""
from typing import Literal, Optional
from fastapi import APIRouter, Query, HTTPException
from loguru import logger

from app.services.scanner import run_scan, get_scan_status


router = APIRouter()


PresetType = Literal[
    "above_ma20", "above_ma50", "breaking_ma20",
    "squeeze", "vpa_setup", "strong_trend", "vol_breakout"
]


@router.get("/scan")
async def scan(
    preset: PresetType = Query(default="above_ma20"),
    exchange: str = Query(default="HOSE"),
    force_refresh: bool = Query(default=False),
):
    """
    Quet thi truong va loc CP theo preset.

    - **preset**: above_ma20, above_ma50, breaking_ma20, squeeze, vpa_setup, strong_trend, vol_breakout
    - **exchange**: HOSE, HNX, ALL
    - **force_refresh**: Bo cache, scan lai tu dau (mat 1-2 phut)
    """
    try:
        result = await run_scan(
            preset=preset,
            exchange=exchange,
            force_refresh=force_refresh,
        )
        return result
    except Exception as e:
        logger.exception(f"Screener scan loi: {e}")
        raise HTTPException(500, f"Loi scan: {str(e)}")


@router.get("/status")
async def scan_status():
    """Trang thai scan dang chay (cho progress UI)."""
    return get_scan_status()


@router.get("/presets")
async def list_presets():
    """Danh sach cac preset co san."""
    return {
        "presets": [
            {"key": "above_ma20", "name": "Vuot MA20", "desc": "Gia tren duong MA20"},
            {"key": "above_ma50", "name": "Vuot MA50", "desc": "Gia tren duong MA50"},
            {"key": "breaking_ma20", "name": "Vua vuot MA20", "desc": "Phien truoc duoi, phien nay tren MA20"},
            {"key": "squeeze", "name": "BB Squeeze", "desc": "Bollinger Bands thu hep - tich luy"},
            {"key": "vpa_setup", "name": "VPA Setup", "desc": "Co tin hieu SOS hoac Spring 5 phien gan"},
            {"key": "strong_trend", "name": "Trend manh", "desc": "ADX > 25 va +DI > -DI"},
            {"key": "vol_breakout", "name": "Vol breakout", "desc": "Volume vuot 2x trung binh MA20"},
        ]
    }