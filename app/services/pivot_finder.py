"""
Pivot Finder - Port chinh xac tu Henry_Full.afl (AmiBroker)
Section: "Pivot Finder" (lines 274-380)

Logic:
- Tinh HHVBars/LLVBars tren cua so n_bars
- Track trend direction (U/D)
- Khi trend doi -> xac nhan Pivot High/Low tai bar dao chieu
- Bonus: detect candidate pivot mới nhất (chưa confirmed)

Buy = Pivot Low (aLPivs)
Sell = Pivot High (aHPivs)
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Dict, List


def _hhv_bars(series: pd.Series, period: int) -> np.ndarray:
    """
    Return so bar tu hien tai ve dinh cao nhat trong window.
    Equivalent AmiBroker HHVBars(H, period).
    """
    n = len(series)
    vals = series.values
    result = np.zeros(n, dtype=int)
    for i in range(n):
        start = max(0, i - period + 1)
        window = vals[start:i+1]
        argmax = np.argmax(window)
        # bars back = (len-1) - argmax
        result[i] = (len(window) - 1) - argmax
    return result


def _llv_bars(series: pd.Series, period: int) -> np.ndarray:
    """Equivalent AmiBroker LLVBars(L, period)."""
    n = len(series)
    vals = series.values
    result = np.zeros(n, dtype=int)
    for i in range(n):
        start = max(0, i - period + 1)
        window = vals[start:i+1]
        argmin = np.argmin(window)
        result[i] = (len(window) - 1) - argmin
    return result


def calculate_pivots(
    df: pd.DataFrame,
    n_bars: int = 12,
    farback: int = 100,
) -> Dict:
    """
    Tinh Pivot High/Low theo AmiBroker AFL.
    
    Args:
        df: DataFrame voi cot open, high, low, close, time (timestamp ms)
        n_bars: So bars lookback de xac nhan pivot (default 12 nhu AFL)
        farback: So bars luc dau de scan (default 100 nhu AFL)
    
    Returns:
        Dict with:
            - pivot_lows: list[{time, price}] - Confirmed pivot lows (BUY signals)
            - pivot_highs: list[{time, price}] - Confirmed pivot highs (SELL signals)
            - last_signal: dict - Latest signal (BUY or SELL)
            - counts: dict
    """
    if df is None or len(df) < n_bars + 5:
        return {
            "params": {"n_bars": n_bars, "farback": farback},
            "pivot_lows": [],
            "pivot_highs": [],
            "last_signal": None,
            "counts": {"buy": 0, "sell": 0},
        }
    
    n = len(df)
    h = df["high"].values
    l = df["low"].values
    o = df["open"].values
    c = df["close"].values
    t = df["time"].values
    
    # HHV/LLV bars
    hhv_bars = _hhv_bars(df["high"], n_bars)
    llv_bars = _llv_bars(df["low"], n_bars)
    
    # AFL: aHHV = HHV(H, nBars), aLLV = LLV(L, nBars)
    hhv = df["high"].rolling(window=n_bars, min_periods=1).max().values
    llv = df["low"].rolling(window=n_bars, min_periods=1).min().values
    
    # Tracking pivot arrays
    aHPivs = np.zeros(n, dtype=bool)  # high pivots (SELL)
    aLPivs = np.zeros(n, dtype=bool)  # low pivots (BUY)
    
    pivot_lows_list = []  # {time, price, idx}
    pivot_highs_list = []
    
    # === AFL main loop ===
    # AFL: for(i=0; i<farback; i++) starting from curBar=BarCount-1 backward
    # Translation: start from last bar, go back `farback` bars
    
    cur_bar = n - 1
    # Determine initial trend
    if llv_bars[cur_bar] < hhv_bars[cur_bar]:
        cur_trend = "D"  # newer low than newer high → downtrend
    else:
        cur_trend = "U"
    
    iterations = min(farback, n)
    
    for i in range(iterations):
        cur_bar = (n - 1) - i
        if cur_bar < 0:
            break
        
        if llv_bars[cur_bar] < hhv_bars[cur_bar]:
            # Newer LLV than HHV → in downtrend
            if cur_trend == "U":
                # Trend changed U -> D, confirm a Pivot LOW
                cur_trend = "D"
                piv_idx = cur_bar - llv_bars[cur_bar]
                if 0 <= piv_idx < n:
                    aLPivs[piv_idx] = True
        else:
            # Newer HHV than LLV → in uptrend
            if cur_trend == "D":
                cur_trend = "U"
                piv_idx = cur_bar - hhv_bars[cur_bar]
                if 0 <= piv_idx < n:
                    aHPivs[piv_idx] = True
    
    # === Candidate pivot (latest swing not yet confirmed) ===
    # AFL section "candIdx, candPrc" - check if current swing high/low qualifies
    cur_bar = n - 1
    
    # Find last confirmed pivot indices
    last_lp_idx = -1
    last_hp_idx = -1
    last_lp_l = 0
    last_hp_h = 0
    
    for j in range(n - 1, -1, -1):
        if aLPivs[j] and last_lp_idx == -1:
            last_lp_idx = j
            last_lp_l = l[j]
        if aHPivs[j] and last_hp_idx == -1:
            last_hp_idx = j
            last_hp_h = h[j]
        if last_lp_idx != -1 and last_hp_idx != -1:
            break
    
    if last_lp_idx > last_hp_idx:
        # Last was low pivot, looking for candidate high
        cand_idx = cur_bar - hhv_bars[cur_bar]
        cand_prc = hhv[cur_bar]
        if last_hp_h < cand_prc and cand_idx > last_lp_idx and cand_idx < cur_bar:
            if 0 <= cand_idx < n:
                aHPivs[cand_idx] = True
    else:
        # Last was high pivot, looking for candidate low
        cand_idx = cur_bar - llv_bars[cur_bar]
        cand_prc = llv[cur_bar]
        if last_lp_l > cand_prc and cand_idx > last_hp_idx and cand_idx < cur_bar:
            if 0 <= cand_idx < n:
                aLPivs[cand_idx] = True
    
    # === Collect all pivots ===
    for i in range(n):
        if aLPivs[i]:
            pivot_lows_list.append({
                "time": int(t[i]),
                "price": float(l[i]),
                "entry_price": float(o[i]),  # AFL uses Open as entry
            })
        if aHPivs[i]:
            pivot_highs_list.append({
                "time": int(t[i]),
                "price": float(h[i]),
                "entry_price": float(o[i]),
            })
    
    # === Determine last signal ===
    # AFL: scan from last bar backward
    last_signal = None
    for i in range(n - 1, 0, -1):
        if aLPivs[i]:
            last_signal = {
                "type": "BUY",
                "time": int(t[i]),
                "price": float(o[i]),
                "bar_index": i,
                "bars_ago": (n - 1) - i,
            }
            break
        if aHPivs[i]:
            last_signal = {
                "type": "SELL",
                "time": int(t[i]),
                "price": float(o[i]),
                "bar_index": i,
                "bars_ago": (n - 1) - i,
            }
            break
    
    return {
        "params": {"n_bars": n_bars, "farback": farback},
        "pivot_lows": pivot_lows_list,
        "pivot_highs": pivot_highs_list,
        "last_signal": last_signal,
        "counts": {
            "buy": len(pivot_lows_list),
            "sell": len(pivot_highs_list),
        },
    }


# Test standalone
if __name__ == "__main__":
    import numpy as np
    np.random.seed(42)
    n = 200
    base = 100
    closes = base + np.cumsum(np.random.randn(n) * 1.5)
    opens = closes - np.random.randn(n) * 0.5
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
    
    result = calculate_pivots(df, n_bars=12)
    print(f"Total bars: {n}")
    print(f"Buy (Pivot Lows): {result['counts']['buy']}")
    print(f"Sell (Pivot Highs): {result['counts']['sell']}")
    print(f"Last signal: {result['last_signal']}")
    
    if result['pivot_lows']:
        print(f"\nFirst 3 Buy pivots:")
        for p in result['pivot_lows'][:3]:
            print(f"  {p}")
    if result['pivot_highs']:
        print(f"\nFirst 3 Sell pivots:")
        for p in result['pivot_highs'][:3]:
            print(f"  {p}")
