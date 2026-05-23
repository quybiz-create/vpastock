"""
REST API endpoints cho Risk Management module.
"""
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

from app.core.risk import (
    calculate_position_size,
    calculate_rr_ratio,
    suggest_atr_stop_loss,
    calculate_setup_score,
)


router = APIRouter()


# ============================================================
# 1. POSITION SIZE
# ============================================================
@router.get("/position-size")
async def api_position_size(
    nav: float = Query(..., gt=0, description="Net Asset Value (VND)"),
    risk_pct: float = Query(2.0, gt=0, le=10, description="% risk per trade (0.1-10)"),
    entry: float = Query(..., gt=0, description="Gia mua du kien"),
    sl: float = Query(..., gt=0, description="Gia stop loss"),
    lot_size: int = Query(100, ge=1, description="Lot size (default 100 cho HoSE)"),
):
    """
    Tinh so co phieu nen mua dua vao NAV va risk per trade.
    
    Example: /api/risk/position-size?nav=100000000&risk_pct=2&entry=89400&sl=84500
    """
    result = calculate_position_size(
        nav=nav,
        risk_pct=risk_pct,
        entry_price=entry,
        stop_loss_price=sl,
        lot_size=lot_size,
    )
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ============================================================
# 2. R:R RATIO
# ============================================================
@router.get("/rr-ratio")
async def api_rr_ratio(
    entry: float = Query(..., gt=0),
    sl: float = Query(..., gt=0),
    target: float = Query(..., gt=0),
):
    """
    Tinh R:R ratio.
    
    Example: /api/risk/rr-ratio?entry=89400&sl=84500&target=99500
    """
    result = calculate_rr_ratio(entry, sl, target)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ============================================================
# 3. ATR STOP LOSS
# ============================================================
@router.get("/atr-sl")
async def api_atr_sl(
    price: float = Query(..., gt=0, description="Gia hien tai"),
    atr: float = Query(..., gt=0, description="ATR(14) value"),
    multiplier: float = Query(2.0, gt=0, le=5, description="ATR multiplier (1.5 intraday, 2 swing, 3 long-term)"),
):
    """
    De xuat stop loss dua vao ATR.
    
    Example: /api/risk/atr-sl?price=89400&atr=2450&multiplier=2
    """
    return suggest_atr_stop_loss(price, atr, multiplier)


# ============================================================
# 4. SETUP QUALITY SCORE
# ============================================================
class SetupScoreInput(BaseModel):
    """Input cho setup quality score (POST body)."""
    vpa_signal: Optional[str] = Field(None, description="SOS/Spring/SOW/UpThrust/NoSupply/NoDemand/Normal")
    vpa_days_ago: int = Field(99, ge=0, description="So phien tu khi co tin hieu VPA")
    price: float = Field(0, ge=0)
    ma20: float = Field(0, ge=0)
    ma50: float = Field(0, ge=0)
    adx: float = Field(0, ge=0)
    plus_di: float = Field(0, ge=0)
    minus_di: float = Field(0, ge=0)
    rsi: float = Field(50, ge=0, le=100)
    vol_vs_ma20_pct: float = Field(0, description="% vol vs MA20")


@router.post("/setup-score")
async def api_setup_score(payload: SetupScoreInput):
    """
    Tinh diem chat luong setup (0-100).
    
    POST /api/risk/setup-score
    Body: {"vpa_signal":"SOS","vpa_days_ago":1,"price":89.4,"ma20":78.35,...}
    """
    result = calculate_setup_score(
        vpa_signal=payload.vpa_signal,
        vpa_days_ago=payload.vpa_days_ago,
        price=payload.price,
        ma20=payload.ma20,
        ma50=payload.ma50,
        adx=payload.adx,
        plus_di=payload.plus_di,
        minus_di=payload.minus_di,
        rsi=payload.rsi,
        vol_vs_ma20_pct=payload.vol_vs_ma20_pct,
    )
    return result


# ============================================================
# 5. FULL CALC (gom tat ca thanh 1 call)
# ============================================================
class FullCalcInput(BaseModel):
    """Input cho full calculation."""
    nav: float = Field(..., gt=0)
    risk_pct: float = Field(2.0, gt=0, le=10)
    entry: float = Field(..., gt=0)
    sl: float = Field(..., gt=0)
    target: float = Field(..., gt=0)
    # Optional: setup score inputs
    vpa_signal: Optional[str] = None
    vpa_days_ago: int = 99
    ma20: float = 0
    ma50: float = 0
    adx: float = 0
    plus_di: float = 0
    minus_di: float = 0
    rsi: float = 50
    vol_vs_ma20_pct: float = 0


@router.post("/full-calc")
async def api_full_calc(payload: FullCalcInput):
    """
    Tinh tat ca cung 1 luc: position size + R:R + setup score.
    """
    # Position size
    pos = calculate_position_size(
        nav=payload.nav,
        risk_pct=payload.risk_pct,
        entry_price=payload.entry,
        stop_loss_price=payload.sl,
    )
    # R:R
    rr = calculate_rr_ratio(payload.entry, payload.sl, payload.target)
    # Setup score
    score = calculate_setup_score(
        vpa_signal=payload.vpa_signal,
        vpa_days_ago=payload.vpa_days_ago,
        price=payload.entry,
        ma20=payload.ma20,
        ma50=payload.ma50,
        adx=payload.adx,
        plus_di=payload.plus_di,
        minus_di=payload.minus_di,
        rsi=payload.rsi,
        vol_vs_ma20_pct=payload.vol_vs_ma20_pct,
    )
    
    return {
        "position_size": pos,
        "rr": rr,
        "setup_score": score,
    }