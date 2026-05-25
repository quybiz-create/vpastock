"""
EMA Cross + SuperTrend indicators
Port chinh xac tu Henry_Full.afl (AmiBroker)

- EMA 20 / EMA 40 + Golden Cross / Death Cross
- SuperTrend: 2-phase (BUY/SELL) with ATR-based bands
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Dict, List


def _ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average (matches AmiBroker EMA)."""
    return series.ewm(span=period, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int = 5) -> pd.Series:
    """Average True Range (matches AmiBroker ATR with Wilder smoothing)."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # AmiBroker uses Wilder's smoothing (alpha=1/period)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def calculate_ema_cross(
    df: pd.DataFrame,
    fast: int = 20,
    slow: int = 40,
) -> Dict:
    """
    Tinh EMA 20/40 + Golden Cross / Death Cross.
    
    Returns:
        ema_fast: list[{time, value}] - EMA20 series
        ema_slow: list[{time, value}] - EMA40 series
        golden_cross: list[{time, price}] - cross UP markers (below bar)
        death_cross: list[{time, price}] - cross DOWN markers (above bar)
    """
    if df is None or len(df) < slow + 2:
        return {
            "ema_fast": [],
            "ema_slow": [],
            "golden_cross": [],
            "death_cross": [],
            "params": {"fast": fast, "slow": slow},
        }
    
    t = df["time"].values
    l = df["low"].values
    h = df["high"].values
    n = len(df)
    
    ema_f = _ema(df["close"], fast)
    ema_s = _ema(df["close"], slow)
    
    # Detect crosses
    diff = ema_f - ema_s
    prev_diff = diff.shift(1)
    
    # Golden cross: prev <= 0 AND current > 0
    golden = (prev_diff <= 0) & (diff > 0)
    # Death cross: prev >= 0 AND current < 0
    death = (prev_diff >= 0) & (diff < 0)
    
    return {
        "params": {"fast": fast, "slow": slow},
        "ema_fast": [
            {"time": int(t[i]), "value": float(ema_f.iloc[i])}
            for i in range(n) if not np.isnan(ema_f.iloc[i])
        ],
        "ema_slow": [
            {"time": int(t[i]), "value": float(ema_s.iloc[i])}
            for i in range(n) if not np.isnan(ema_s.iloc[i])
        ],
        "golden_cross": [
            {"time": int(t[i]), "price": float(l[i])}
            for i in range(n) if golden.iloc[i] and not np.isnan(golden.iloc[i])
        ],
        "death_cross": [
            {"time": int(t[i]), "price": float(h[i])}
            for i in range(n) if death.iloc[i] and not np.isnan(death.iloc[i])
        ],
        "counts": {
            "golden_cross": int(golden.fillna(False).sum()),
            "death_cross": int(death.fillna(False).sum()),
        },
    }


def calculate_supertrend(
    df: pd.DataFrame,
    period: int = 5,
    multiplier: float = 2.0,
) -> Dict:
    """
    Tinh SuperTrend theo AFL Henry_Full.
    
    Logic AFL:
    - 2 phases: PHASE_BUY (+1), PHASE_SELL (-1), PHASE_NONE (0)
    - band_upper = CalcPrice + ATR_Multiplier * tr
    - band_lower = CalcPrice - ATR_Multiplier * tr
    - CalcPrice = (H + L) / 2
    
    Phase changes:
    - BUY when Close > line_down[prev]
    - SELL when Close < line_up[prev]
    
    Lines:
    - line_up (uptrend) = band_lower, clamped to never decrease in BUY phase
    - line_down (downtrend) = band_upper, clamped to never increase in SELL phase
    
    Returns:
        line_up: list[{time, value}] - xanh, below price khi uptrend
        line_down: list[{time, value}] - do, above price khi downtrend
        buy_signals: list[{time, price}] - khi switch sang BUY
        sell_signals: list[{time, price}] - khi switch sang SELL
    """
    if df is None or len(df) < period + 2:
        return {
            "params": {"period": period, "multiplier": multiplier},
            "line_up": [],
            "line_down": [],
            "buy_signals": [],
            "sell_signals": [],
            "counts": {"buy": 0, "sell": 0},
        }
    
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    t = df["time"].values
    n = len(df)
    
    # ATR
    tr = _atr(df, period).values
    
    # CalcPrice = (H+L)/2
    calc_price = (h + l) / 2
    
    # Initialize buffers (NaN by default)
    line_up = np.full(n, np.nan)
    line_down = np.full(n, np.nan)
    
    # Phase: 0=none, 1=buy, -1=sell
    phase = 0
    
    # Track phase transitions for signals
    buy_signals = []
    sell_signals = []
    
    for i in range(period + 1, n):
        band_upper = calc_price[i] + multiplier * tr[i]
        band_lower = calc_price[i] - multiplier * tr[i]
        
        # First bar: init both
        if phase == 0:
            line_up[i] = calc_price[i]
            line_down[i] = calc_price[i]
        
        # Phase transition: SELL -> BUY (or NONE -> BUY)
        prev_line_down = line_down[i-1]
        if phase != 1 and c[i] > prev_line_down and not np.isnan(prev_line_down):
            phase = 1
            line_up[i] = band_lower
            line_up[i-1] = prev_line_down  # smooth transition
            buy_signals.append({"time": int(t[i]), "price": float(l[i])})
        
        # Phase transition: BUY -> SELL (or NONE -> SELL)
        prev_line_up = line_up[i-1]
        if phase != -1 and c[i] < prev_line_up and not np.isnan(prev_line_up):
            phase = -1
            line_down[i] = band_upper
            line_down[i-1] = prev_line_up
            sell_signals.append({"time": int(t[i]), "price": float(h[i])})
        
        # Continue BUY phase: line_up is max(band_lower, prev_line_up)
        if phase == 1 and not np.isnan(line_up[i-1]):
            if band_lower > line_up[i-1]:
                line_up[i] = band_lower
            else:
                line_up[i] = line_up[i-1]
        
        # Continue SELL phase: line_down is min(band_upper, prev_line_down)
        if phase == -1 and not np.isnan(line_down[i-1]):
            if band_upper < line_down[i-1]:
                line_down[i] = band_upper
            else:
                line_down[i] = line_down[i-1]
    
    return {
        "params": {"period": period, "multiplier": multiplier},
        "line_up": [
            {"time": int(t[i]), "value": float(line_up[i])}
            for i in range(n) if not np.isnan(line_up[i])
        ],
        "line_down": [
            {"time": int(t[i]), "value": float(line_down[i])}
            for i in range(n) if not np.isnan(line_down[i])
        ],
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "counts": {
            "buy": len(buy_signals),
            "sell": len(sell_signals),
        },
    }


# Test standalone
if __name__ == "__main__":
    import numpy as np
    np.random.seed(42)
    n = 300
    base = 100
    closes = base + np.cumsum(np.random.randn(n) * 2)
    opens = closes - np.random.randn(n) * 0.8
    highs = np.maximum(opens, closes) + np.abs(np.random.randn(n))
    lows = np.minimum(opens, closes) - np.abs(np.random.randn(n))
    times = [1748000000000 + i * 86400000 for i in range(n)]
    
    df = pd.DataFrame({
        "time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
    })
    
    # Test EMA Cross
    print("=" * 50)
    print("EMA 20/40 Cross")
    print("=" * 50)
    ema_result = calculate_ema_cross(df)
    print(f"EMA20 points: {len(ema_result['ema_fast'])}")
    print(f"EMA40 points: {len(ema_result['ema_slow'])}")
    print(f"Golden cross: {ema_result['counts']['golden_cross']}")
    print(f"Death cross: {ema_result['counts']['death_cross']}")
    if ema_result['golden_cross']:
        print(f"First golden: {ema_result['golden_cross'][0]}")
    if ema_result['death_cross']:
        print(f"First death: {ema_result['death_cross'][0]}")
    
    # Test SuperTrend
    print("\n" + "=" * 50)
    print("SuperTrend (5, 2.0)")
    print("=" * 50)
    st_result = calculate_supertrend(df)
    print(f"Line UP points: {len(st_result['line_up'])}")
    print(f"Line DOWN points: {len(st_result['line_down'])}")
    print(f"Buy signals: {st_result['counts']['buy']}")
    print(f"Sell signals: {st_result['counts']['sell']}")
    if st_result['buy_signals']:
        print(f"First buy: {st_result['buy_signals'][0]}")
    if st_result['sell_signals']:
        print(f"First sell: {st_result['sell_signals'][0]}")
