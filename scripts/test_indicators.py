"""Test nhanh indicators module."""
import sys
sys.path.insert(0, "/home/claude/vpastock/backend")

import numpy as np
import pandas as pd
from app.core.indicators import (
    compute_all, is_above_ma, is_breaking_ma, is_squeeze,
    is_vpa_setup, is_strong_trend, vpa_signal
)

np.random.seed(42)
dates = pd.date_range("2025-12-01", periods=100, freq="B")
price = 200.0
data = []
for i in range(100):
    noise = np.random.normal(0, 1.5)
    if i >= 95:
        noise = abs(noise) + 1.5
    o = price
    c = price + noise
    h = max(o, c) + abs(np.random.normal(0, 0.8))
    l = min(o, c) - abs(np.random.normal(0, 0.8))
    v = 3_000_000 + np.random.randint(-500_000, 2_000_000)
    if i >= 95:
        v = 8_000_000 + np.random.randint(0, 2_000_000)
    data.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
    price = c

df = pd.DataFrame(data, index=dates)
result = compute_all(df)
last = result.iloc[-1]

print("=" * 60)
print("VPASTOCK - Test Indicators")
print("=" * 60)
print(f"\nGiá cuối: {df['close'].iloc[-1]:.2f}")
print(f"Vol cuối: {df['volume'].iloc[-1]:,.0f}")
print(f"\nMA20:  {last['ma20']:.2f}")
print(f"MA50:  {last['ma50']:.2f}")
print(f"RSI:   {last['rsi']:.2f}")
print(f"MFI:   {last['mfi']:.2f}")
print(f"ADX:   {last['adx']:.2f}  +DI: {last['plus_di']:.2f}  -DI: {last['minus_di']:.2f}")
print(f"VPA:   {last['vpa']}")
print(f"\nTrên MA20:        {is_above_ma(df, 20)}")
print(f"VPA setup mạnh:   {is_vpa_setup(df)}")
print(f"Xu hướng mạnh:    {is_strong_trend(df)}")
print("\n✓ Indicators chạy không lỗi")
