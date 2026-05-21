"""
Trading calendar va T+2 settlement cho thi truong chung khoan VN.
Quy dinh tu 29/08/2022 (VSDC): T+2 - CP ve truoc 13h00 ngay T+2, ban duoc chieu T+2.
"""
from __future__ import annotations
from datetime import date, datetime, time, timedelta
from typing import List, Dict, Optional
from enum import Enum


VN_HOLIDAYS = {
    date(2026, 1, 1): "Tet Duong lich",
    date(2026, 2, 16): "Mong 1 Tet Binh Ngo",
    date(2026, 2, 17): "Mong 2 Tet Binh Ngo",
    date(2026, 2, 18): "Mong 3 Tet Binh Ngo",
    date(2026, 2, 19): "Mong 4 Tet Binh Ngo",
    date(2026, 2, 20): "Mong 5 Tet Binh Ngo",
    date(2026, 4, 27): "Gio To Hung Vuong",
    date(2026, 4, 30): "Giai phong Mien Nam",
    date(2026, 5, 1): "Quoc te Lao dong",
    date(2026, 9, 2): "Quoc khanh",
    date(2026, 9, 3): "Bu Quoc khanh",
    date(2027, 1, 1): "Tet Duong lich",
    date(2027, 2, 5): "Tet Am lich",
    date(2027, 2, 6): "Tet Am lich",
    date(2027, 2, 7): "Tet Am lich",
    date(2027, 2, 8): "Tet Am lich",
    date(2027, 2, 9): "Tet Am lich",
    date(2027, 4, 16): "Gio To",
    date(2027, 4, 30): "Giai phong Mien Nam",
    date(2027, 5, 1): "Quoc te Lao dong",
    date(2027, 9, 2): "Quoc khanh",
}


class WarningLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def is_holiday(d: date) -> bool:
    return d in VN_HOLIDAYS


def is_trading_day(d: date) -> bool:
    return not is_weekend(d) and not is_holiday(d)


def next_trading_day(d: date) -> date:
    next_d = d + timedelta(days=1)
    while not is_trading_day(next_d):
        next_d += timedelta(days=1)
    return next_d


def add_trading_days(start: date, n: int) -> date:
    if n <= 0:
        return start
    current = start
    days_added = 0
    while days_added < n:
        current = next_trading_day(current)
        days_added += 1
    return current


def count_calendar_days(start: date, end: date) -> int:
    return (end - start).days


def get_holidays_between(start: date, end: date) -> List[Dict]:
    result = []
    for holiday_date, name in VN_HOLIDAYS.items():
        if start < holiday_date <= end:
            result.append({"date": holiday_date.isoformat(), "name": name})
    return sorted(result, key=lambda x: x["date"])


WEEKDAY_VN = ["Thu 2", "Thu 3", "Thu 4", "Thu 5", "Thu 6", "Thu 7", "Chu nhat"]


def _weekday_vn(d: date) -> str:
    return WEEKDAY_VN[d.weekday()]


def _format_date_vn(d: date) -> str:
    return f"{_weekday_vn(d)} {d.day:02d}/{d.month:02d}/{d.year}"


def get_settlement_info(buy_date: Optional[date] = None) -> Dict:
    if buy_date is None:
        buy_date = date.today()
    
    if not is_trading_day(buy_date):
        if is_weekend(buy_date):
            warning = f"Ngay {buy_date} la cuoi tuan, khong giao dich."
        else:
            warning = f"Ngay {buy_date} la ngay le ({VN_HOLIDAYS[buy_date]})."
        return {
            "buy_date": buy_date.isoformat(),
            "buy_weekday": _weekday_vn(buy_date),
            "is_trading_day": False,
            "warning_level": WarningLevel.HIGH,
            "warning_message": warning,
            "cp_arrival_date": None,
            "sellable_from": None,
        }
    
    cp_arrival_date = add_trading_days(buy_date, 2)
    sellable_from = datetime.combine(cp_arrival_date, time(13, 0))
    
    trading_days_locked = 2
    calendar_days_locked = count_calendar_days(buy_date, cp_arrival_date)
    
    weekend_in_period = False
    check = buy_date + timedelta(days=1)
    while check <= cp_arrival_date:
        if is_weekend(check):
            weekend_in_period = True
            break
        check += timedelta(days=1)
    
    holidays_in_period = get_holidays_between(buy_date, cp_arrival_date)
    
    if holidays_in_period and calendar_days_locked >= 5:
        warning_level = WarningLevel.HIGH
        warning_message = (
            f"CP khoa {calendar_days_locked} ngay duong lich do dinh "
            f"{len(holidays_in_period)} ngay le. Rui ro cao."
        )
    elif weekend_in_period or holidays_in_period:
        warning_level = WarningLevel.MEDIUM
        reasons = []
        if weekend_in_period:
            reasons.append("cuoi tuan")
        if holidays_in_period:
            reasons.append(f"{len(holidays_in_period)} ngay le")
        warning_message = (
            f"CP khoa {calendar_days_locked} ngay duong lich do dinh "
            f"{' + '.join(reasons)}."
        )
    else:
        warning_level = WarningLevel.LOW
        warning_message = (
            f"CP ve TK chieu {_format_date_vn(cp_arrival_date)} (sau 13h00). "
            f"Khoa 2 ngay giao dich binh thuong."
        )
    
    return {
        "buy_date": buy_date.isoformat(),
        "buy_weekday": _weekday_vn(buy_date),
        "is_trading_day": True,
        "cp_arrival_date": cp_arrival_date.isoformat(),
        "cp_arrival_weekday": _weekday_vn(cp_arrival_date),
        "sellable_from": sellable_from.isoformat(),
        "sellable_from_human": f"{_format_date_vn(cp_arrival_date)} sau 13:00",
        "trading_days_locked": trading_days_locked,
        "calendar_days_locked": calendar_days_locked,
        "weekend_in_period": weekend_in_period,
        "holidays_in_period": holidays_in_period,
        "warning_level": warning_level,
        "warning_message": warning_message,
    }


def get_sell_settlement_info(sell_date: Optional[date] = None) -> Dict:
    if sell_date is None:
        sell_date = date.today()
    
    if not is_trading_day(sell_date):
        return {
            "sell_date": sell_date.isoformat(),
            "is_trading_day": False,
            "warning_message": f"Ngay {sell_date} khong phai ngay giao dich.",
        }
    
    money_arrival_date = add_trading_days(sell_date, 2)
    
    return {
        "sell_date": sell_date.isoformat(),
        "sell_weekday": _weekday_vn(sell_date),
        "is_trading_day": True,
        "money_arrival_date": money_arrival_date.isoformat(),
        "money_arrival_weekday": _weekday_vn(money_arrival_date),
        "money_arrival_human": f"{_format_date_vn(money_arrival_date)} chieu",
        "calendar_days_to_money": count_calendar_days(sell_date, money_arrival_date),
    }