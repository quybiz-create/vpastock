"""
Risk Management module cho vpastock.

Cac tinh nang:
1. Position size calculator (NAV + risk%)
2. ATR-based stop loss suggestion
3. R:R ratio calculator
4. Setup quality score (0-100, 5 yeu to confluence)
"""
from __future__ import annotations
from typing import Dict, Optional, List
from enum import Enum


class SetupQuality(str, Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    AVERAGE = "average"
    WEAK = "weak"


# ============================================================
# 1. POSITION SIZE CALCULATOR
# ============================================================
def calculate_position_size(
    nav: float,
    risk_pct: float,
    entry_price: float,
    stop_loss_price: float,
    lot_size: int = 100,
) -> Dict:
    if entry_price <= stop_loss_price:
        return {"error": "Stop loss phai THAP HON entry price", "shares": 0}
    if risk_pct <= 0 or risk_pct > 10:
        return {"error": "Risk per trade phai trong khoang 0.1% - 10%", "shares": 0}

    max_loss_vnd = nav * (risk_pct / 100)
    risk_per_share = entry_price - stop_loss_price
    raw_shares = max_loss_vnd / risk_per_share
    shares = int(raw_shares // lot_size) * lot_size

    if shares == 0:
        return {
            "error": f"NAV qua nho. Toi thieu {lot_size} CP can {lot_size * risk_per_share:,.0f} VND risk.",
            "shares": 0,
        }

    capital_used = shares * entry_price
    actual_max_loss = shares * risk_per_share
    capital_pct = (capital_used / nav) * 100

    return {
        "nav": nav,
        "risk_pct": risk_pct,
        "entry_price": entry_price,
        "stop_loss_price": stop_loss_price,
        "shares": shares,
        "shares_human": f"{shares:,} CP",
        "capital_used": round(capital_used, 0),
        "capital_used_human": f"{capital_used:,.0f} VND",
        "capital_pct": round(capital_pct, 2),
        "max_loss": round(actual_max_loss, 0),
        "max_loss_human": f"{actual_max_loss:,.0f} VND",
        "risk_per_share": round(risk_per_share, 2),
        "risk_per_share_pct": round((risk_per_share / entry_price) * 100, 2),
    }


# ============================================================
# 2. R:R RATIO
# ============================================================
def calculate_rr_ratio(entry_price: float, stop_loss_price: float, target_price: float) -> Dict:
    if entry_price <= stop_loss_price:
        return {"error": "SL phai THAP HON entry"}
    if target_price <= entry_price:
        return {"error": "Target phai CAO HON entry"}

    risk = entry_price - stop_loss_price
    reward = target_price - entry_price
    rr = reward / risk
    risk_pct = (risk / entry_price) * 100
    reward_pct = (reward / entry_price) * 100

    if rr >= 3.0:
        quality = "excellent"
        quality_msg = "R:R rat tot (>= 1:3)"
    elif rr >= 2.0:
        quality = "good"
        quality_msg = "R:R tot (1:2 - 1:3)"
    elif rr >= 1.5:
        quality = "acceptable"
        quality_msg = "R:R chap nhan duoc (1:1.5 - 1:2)"
    else:
        quality = "poor"
        quality_msg = "R:R thap (< 1:1.5) - khong nen vao lenh"

    return {
        "entry_price": entry_price,
        "stop_loss_price": stop_loss_price,
        "target_price": target_price,
        "risk_vnd": round(risk, 2),
        "reward_vnd": round(reward, 2),
        "risk_pct": round(risk_pct, 2),
        "reward_pct": round(reward_pct, 2),
        "rr_ratio": round(rr, 2),
        "rr_ratio_human": f"1 : {rr:.2f}",
        "quality": quality,
        "quality_msg": quality_msg,
    }


# ============================================================
# 3. ATR STOP LOSS
# ============================================================
def suggest_atr_stop_loss(current_price: float, atr_value: float, multiplier: float = 2.0) -> Dict:
    if current_price <= 0 or atr_value <= 0:
        return {"error": "current_price va atr_value phai > 0"}

    sl_price = current_price - (atr_value * multiplier)
    sl_pct = ((current_price - sl_price) / current_price) * 100

    if sl_pct < 2:
        recommendation = "SL qua chat (< 2%). Tang multiplier hoac doi setup."
    elif sl_pct > 15:
        recommendation = "SL qua rong (> 15%). ATR cao - market bien dong."
    else:
        recommendation = f"SL hop ly: -{sl_pct:.2f}% tu gia hien tai."

    return {
        "current_price": current_price,
        "atr_value": round(atr_value, 2),
        "multiplier": multiplier,
        "stop_loss_price": round(sl_price, 2),
        "sl_distance_vnd": round(atr_value * multiplier, 2),
        "sl_distance_pct": round(sl_pct, 2),
        "recommendation": recommendation,
    }


# ============================================================
# 4. SETUP QUALITY SCORE
# ============================================================
def calculate_setup_score(
    vpa_signal: Optional[str] = None,
    vpa_days_ago: int = 99,
    price: float = 0,
    ma20: float = 0,
    ma50: float = 0,
    adx: float = 0,
    plus_di: float = 0,
    minus_di: float = 0,
    rsi: float = 50,
    vol_vs_ma20_pct: float = 0,
) -> Dict:
    breakdown = {}

    # 1. VPA Signal (25 pts)
    vpa_pts = 0
    vpa_note = ""
    if vpa_signal:
        sig = vpa_signal.lower()
        if sig in ("upthrust", "sow"):
            vpa_pts = 0
            vpa_note = f"{vpa_signal} - CAM vao lenh"
        elif sig in ("sos", "spring"):
            if vpa_days_ago <= 1:
                vpa_pts = 25
                vpa_note = f"{vpa_signal} hom nay - max diem"
            elif vpa_days_ago <= 3:
                vpa_pts = 18
                vpa_note = f"{vpa_signal} trong 3 phien gan"
            elif vpa_days_ago <= 5:
                vpa_pts = 12
                vpa_note = f"{vpa_signal} trong 5 phien gan"
            else:
                vpa_pts = 5
                vpa_note = f"{vpa_signal} qua xa (>5 phien)"
        elif sig == "nosupply":
            vpa_pts = 8
            vpa_note = "NoSupply - cung can"
        elif sig == "nodemand":
            vpa_pts = 3
            vpa_note = "NoDemand - canh giac"
        else:
            vpa_pts = 5
            vpa_note = "Normal"
    breakdown["vpa"] = {"score": vpa_pts, "max": 25, "note": vpa_note}

    # 2. MA position (20 pts)
    ma_pts = 0
    ma_note = ""
    if price > 0 and ma20 > 0 and ma50 > 0:
        if price > ma20 and price > ma50:
            ma_pts = 20
            ma_note = "Gia > MA20 va MA50 - uptrend xac nhan"
        elif price > ma20 and price <= ma50:
            ma_pts = 12
            ma_note = "Gia > MA20 nhung < MA50"
        elif price > ma50:
            ma_pts = 8
            ma_note = "Gia > MA50 nhung < MA20 - pullback"
        else:
            ma_pts = 3
            ma_note = "Gia < MA20 va MA50 - downtrend"
    breakdown["ma"] = {"score": ma_pts, "max": 20, "note": ma_note}

    # 3. ADX (20 pts)
    adx_pts = 0
    adx_note = ""
    if adx > 0:
        is_bull = plus_di > minus_di
        if adx >= 25 and is_bull:
            adx_pts = 20
            adx_note = f"ADX {adx:.1f} + DI bullish - trend manh"
        elif adx >= 20 and is_bull:
            adx_pts = 12
            adx_note = f"ADX {adx:.1f} - trend dang hinh thanh"
        elif adx < 20:
            adx_pts = 5
            adx_note = f"ADX {adx:.1f} - sideways"
        else:
            adx_pts = 0
            adx_note = f"ADX {adx:.1f} bearish"
    breakdown["adx"] = {"score": adx_pts, "max": 20, "note": adx_note}

    # 4. RSI (15 pts)
    rsi_pts = 0
    rsi_note = ""
    if rsi > 0:
        if 50 <= rsi <= 70:
            rsi_pts = 15
            rsi_note = f"RSI {rsi:.1f} - manh chua qua mua"
        elif 40 <= rsi < 50 or 70 < rsi <= 75:
            rsi_pts = 10
            rsi_note = f"RSI {rsi:.1f} - chap nhan duoc"
        elif 30 <= rsi < 40 or 75 < rsi <= 80:
            rsi_pts = 5
            rsi_note = f"RSI {rsi:.1f} - canh giac extreme"
        else:
            rsi_pts = 0
            rsi_note = f"RSI {rsi:.1f} - extreme rui ro"
    breakdown["rsi"] = {"score": rsi_pts, "max": 15, "note": rsi_note}

    # 5. Volume (20 pts)
    vol_pts = 0
    vol_note = ""
    if vol_vs_ma20_pct >= 50:
        vol_pts = 20
        vol_note = f"Vol +{vol_vs_ma20_pct:.0f}% - Big Money vao manh"
    elif vol_vs_ma20_pct >= 30:
        vol_pts = 15
        vol_note = f"Vol +{vol_vs_ma20_pct:.0f}% - dong tien vao"
    elif vol_vs_ma20_pct >= 0:
        vol_pts = 8
        vol_note = f"Vol +{vol_vs_ma20_pct:.0f}% - binh thuong"
    elif vol_vs_ma20_pct >= -30:
        vol_pts = 3
        vol_note = f"Vol {vol_vs_ma20_pct:.0f}% - mat quan tam"
    else:
        vol_pts = 0
        vol_note = f"Vol {vol_vs_ma20_pct:.0f}% - cuc yeu"
    breakdown["volume"] = {"score": vol_pts, "max": 20, "note": vol_note}

    total = vpa_pts + ma_pts + adx_pts + rsi_pts + vol_pts

    # === OVERRIDE RULES ===
    override_reason = None
    is_blocked = False
    if vpa_signal and vpa_signal.lower() in ("upthrust", "sow"):
        is_blocked = True
        override_reason = f"VPA {vpa_signal} - CAM vao lenh long bat ke cac yeu to khac"
    elif adx >= 25 and plus_di > 0 and minus_di > plus_di:
        is_blocked = True
        override_reason = f"ADX {adx:.1f} bearish (-DI > +DI) - downtrend manh, khong long"

    rsi_cap = (rsi > 0 and (rsi < 30 or rsi > 80))

    # Determine quality - LUON gan quality o moi nhanh
    if is_blocked:
        quality = SetupQuality.WEAK
        recommendation = f"Setup yeu - {override_reason}. Tranh vao lenh."
    elif rsi_cap and total >= 60:
        quality = SetupQuality.AVERAGE
        recommendation = f"RSI extreme ({rsi:.1f}) - dong dieu chinh ngay. Cho confirm them."
    elif total >= 80:
        quality = SetupQuality.EXCELLENT
        recommendation = "Setup xuat sac - vao lenh voi position 10-12% NAV"
    elif total >= 60:
        quality = SetupQuality.GOOD
        recommendation = "Setup tot - vao lenh voi position 5-8% NAV"
    elif total >= 40:
        quality = SetupQuality.AVERAGE
        recommendation = "Setup trung binh - cho confirm them hoac position nho 3%"
    else:
        quality = SetupQuality.WEAK
        recommendation = "Setup yeu - khong nen vao lenh"

    return {
        "total_score": total,
        "quality": quality,
        "recommendation": recommendation,
        "breakdown": breakdown,
        "max_possible": 100,
    }


# ============================================================
# 5. ATR CALCULATION HELPER
# ============================================================
def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.0

    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1]),
        )
        trs.append(tr)

    if len(trs) < period:
        return sum(trs) / len(trs)

    return sum(trs[-period:]) / period
