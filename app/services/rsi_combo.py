"""
RSI Combo System - Port chinh xac tu Pine Script
Pine Script source: RSI Trading System by HamidBox + Libertus

Logic:
1. Advanced RSI Signals (Bull/Bear Engulfing + RSI Oversold/Overbought)
2. RSI Divergence (rolling max/min over xbars=90)
3. Combo: Div + recent RSI signal within comboLookback=10 bars
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Dict, List


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Standard RSI - Wilder's smoothing (matches Pine Script rsi())."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    # Wilder's smoothing = EMA with alpha=1/period
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_rsi_combo(
    df: pd.DataFrame,
    rsi_length: int = 14,
    rsi_ob: int = 70,
    rsi_os: int = 30,
    fib_level: float = 0.333,
    div_lookback: int = 90,    # xbars in Pine
    combo_lookback: int = 10,
) -> Dict[str, List[Dict]]:
    """
    Tinh RSI Combo signals theo PineScript.
    
    Returns dict voi 6 keys, moi key la list of {time, price}.
    """
    if df is None or len(df) < div_lookback + 5:
        return {
            "rsi_buy": [],
            "rsi_exit": [],
            "bull_div": [],
            "bear_div": [],
            "combo_buy": [],
            "combo_exit": [],
        }
    
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    t = df["time"].values
    n = len(df)
    
    # === RSI ===
    rsi = _rsi(df["close"], rsi_length).values
    rsi_overbought = rsi >= rsi_ob
    rsi_oversold = rsi <= rsi_os
    
    # === Engulfing (Pine: bullE = close > open[1] AND close[1] < open[1]) ===
    # bullE[i]: current bullish, prev bearish, current close > prev open
    bull_e = np.zeros(n, dtype=bool)
    bear_e = np.zeros(n, dtype=bool)
    for i in range(1, n):
        # Pine bullE: close > open[1] and close[1] < open[1]
        if c[i] > o[i-1] and c[i-1] < o[i-1]:
            bull_e[i] = True
        # Pine bearE: close < open[1] and close[1] > open[1]
        if c[i] < o[i-1] and c[i-1] > o[i-1]:
            bear_e[i] = True
    
    # === RSI Buy/Exit Signals (Pine: TradeSignal AND bullE/bearE) ===
    # TradeSignal = (rsiOS or rsiOS[1]) and bullE  OR  (rsiOB or rsiOB[1]) and bearE
    rsi_buy_sig = np.zeros(n, dtype=bool)
    rsi_exit_sig = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if np.isnan(rsi[i]) or np.isnan(rsi[i-1]):
            continue
        # Bull signal: (rsiOS[i] or rsiOS[i-1]) AND bullE[i]
        if (rsi_oversold[i] or rsi_oversold[i-1]) and bull_e[i]:
            rsi_buy_sig[i] = True
        # Bear signal: (rsiOB[i] or rsiOB[i-1]) AND bearE[i]
        if (rsi_overbought[i] or rsi_overbought[i-1]) and bear_e[i]:
            rsi_exit_sig[i] = True
    
    # === Divergence (Pine rolling max/min over xbars) ===
    # max[i] = rolling max of close over xbars window
    # max_rsi[i] = rolling max of rsi over xbars window
    # Same for min
    
    # Vectorized rolling max/min using pandas
    close_series = pd.Series(c)
    rsi_series = pd.Series(rsi)
    
    # Pine uses backward-looking window: highestbars(divRsi, xbars) - returns offset of highest in last xbars
    # Equivalent: rolling max with min_periods=1
    rolling_max_close = close_series.rolling(window=div_lookback, min_periods=1).max().values
    rolling_max_rsi = rsi_series.rolling(window=div_lookback, min_periods=1).max().values
    rolling_min_close = close_series.rolling(window=div_lookback, min_periods=1).min().values
    rolling_min_rsi = rsi_series.rolling(window=div_lookback, min_periods=1).min().values
    
    # Pine logic (with anti-repaint shift):
    # divbear at [i]: (max[i-1] > max[i-2]) AND (divRsi[i-1] < max_rsi[i]) AND (divRsi[i] <= divRsi[i-1])
    # divbull at [i]: (min[i-1] < min[i-2]) AND (divRsi[i-1] > min_rsi[i]) AND (divRsi[i] >= divRsi[i-1])
    bull_div = np.zeros(n, dtype=bool)
    bear_div = np.zeros(n, dtype=bool)
    for i in range(2, n):
        if np.isnan(rsi[i]) or np.isnan(rsi[i-1]):
            continue
        # Bear div: price made HH, RSI made LH
        if (rolling_max_close[i-1] > rolling_max_close[i-2]
            and rsi[i-1] < rolling_max_rsi[i]
            and rsi[i] <= rsi[i-1]):
            bear_div[i] = True
        # Bull div: price made LL, RSI made HL
        if (rolling_min_close[i-1] < rolling_min_close[i-2]
            and rsi[i-1] > rolling_min_rsi[i]
            and rsi[i] >= rsi[i-1]):
            bull_div[i] = True
    
    # === Combo (Pine: divbull AND any rsiBuySignal in last comboLookback bars) ===
    # for i = 0 to comboLookback: hadRecentBuy := hadRecentBuy or rsiBuySignal[i]
    # comboBuy = divbull and hadRecentBuy
    combo_buy = np.zeros(n, dtype=bool)
    combo_exit = np.zeros(n, dtype=bool)
    for i in range(n):
        if bull_div[i]:
            # Check rsi_buy_sig in last comboLookback+1 bars (bar [i-lookback] to bar [i])
            start = max(0, i - combo_lookback)
            if rsi_buy_sig[start:i+1].any():
                combo_buy[i] = True
        if bear_div[i]:
            start = max(0, i - combo_lookback)
            if rsi_exit_sig[start:i+1].any():
                combo_exit[i] = True
    
    # === Output ===
    def _to_list(mask, price_arr):
        return [
            {"time": int(t[i]), "price": float(price_arr[i])}
            for i in range(n) if mask[i]
        ]
    
    return {
        "rsi_buy": _to_list(rsi_buy_sig, l),       # below bar
        "rsi_exit": _to_list(rsi_exit_sig, h),     # above bar
        "bull_div": _to_list(bull_div, l),         # below bar
        "bear_div": _to_list(bear_div, h),         # above bar
        "combo_buy": _to_list(combo_buy, l),       # below bar - HIGHLIGHT
        "combo_exit": _to_list(combo_exit, h),     # above bar - HIGHLIGHT
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
    
    result = calculate_rsi_combo(df)
    print(f"Total bars: {n}")
    for key, signals in result.items():
        print(f"  {key}: {len(signals)} signals")
    
    if result["combo_buy"]:
        print(f"\nFirst combo_buy: {result['combo_buy'][0]}")
    if result["combo_exit"]:
        print(f"First combo_exit: {result['combo_exit'][0]}")
    if result["rsi_buy"]:
        print(f"First rsi_buy: {result['rsi_buy'][0]}")
