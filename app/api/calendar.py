"""
API endpoints cho T+2 settlement va trading calendar VN.
"""
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from loguru import logger

from app.core.calendar import (
    get_settlement_info,
    get_sell_settlement_info,
    is_trading_day,
    is_weekend,
    is_holiday,
    next_trading_day,
    VN_HOLIDAYS,
)


router = APIRouter()


def _parse_date(date_str: Optional[str]) -> Optional[date]:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, f"Ngay khong hop le: {date_str}. Dung dinh dang YYYY-MM-DD.")


@router.get("/buy")
async def settlement_buy(
    buy_date: Optional[str] = Query(default=None, description="Ngay mua YYYY-MM-DD"),
):
    """Tinh T+2 settlement khi MUA cổ phiếu."""
    d = _parse_date(buy_date)
    return get_settlement_info(d)


@router.get("/sell")
async def settlement_sell(
    sell_date: Optional[str] = Query(default=None, description="Ngay ban YYYY-MM-DD"),
):
    """Tinh khi nao tien ve TK sau khi BAN (T+2)."""
    d = _parse_date(sell_date)
    return get_sell_settlement_info(d)


@router.get("/check")
async def check_trading_day(
    target_date: str = Query(..., description="Ngay can kiem tra YYYY-MM-DD"),
):
    """Kiem tra 1 ngay co phai ngay giao dich khong."""
    d = _parse_date(target_date)
    if d is None:
        raise HTTPException(400, "Vui long cung cap target_date")
    
    return {
        "date": d.isoformat(),
        "is_trading_day": is_trading_day(d),
        "is_weekend": is_weekend(d),
        "is_holiday": is_holiday(d),
        "holiday_name": VN_HOLIDAYS.get(d),
        "next_trading_day": next_trading_day(d).isoformat() if not is_trading_day(d) else None,
    }


@router.get("/holidays")
async def list_holidays(
    year: Optional[int] = Query(default=None, description="Nam"),
):
    """Liet ke cac ngay le VN trong nam."""
    if year is None:
        year = date.today().year
    
    weekdays = ["Thu 2", "Thu 3", "Thu 4", "Thu 5", "Thu 6", "Thu 7", "Chu nhat"]
    result = [
        {"date": d.isoformat(), "name": name, "weekday": weekdays[d.weekday()]}
        for d, name in VN_HOLIDAYS.items()
        if d.year == year
    ]
    return {
        "year": year,
        "total": len(result),
        "holidays": sorted(result, key=lambda x: x["date"]),
    }