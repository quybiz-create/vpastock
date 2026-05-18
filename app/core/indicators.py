"""Indicators và chỉ báo kỹ thuật."""
from __future__ import annotations
from typing import Optional
import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    return pd.DataFrame({
        "macd": macd_line,
        "signal": signal_line,
        "histogram": macd_line - signal_line,
    })


def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    money_flow = typical_price * df["volume"]
    delta = typical_price.diff()
    positive_flow = money_flow.where(delta > 0, 0).rolling(period).sum()
    negative_flow = money_flow.where(delta < 0, 0).rolling(period).sum()
    result = pd.Series(np.nan, index=df.index)
    mask_valid = positive_flow.notna() & negative_flow.notna()
    only_pos = mask_valid & (negative_flow == 0) & (positive_flow > 0)
    only_neg = mask_valid & (positive_flow == 0) & (negative_flow > 0)
    both = mask_valid & (positive_flow > 0) & (negative_flow > 0)
    result[only_pos] = 100.0
    result[only_neg] = 0.0
    ratio = positive_flow / negative_flow
    result[both] = 100 - (100 / (1 + ratio[both]))
    return result


def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    middle = sma(series, period)
    std = series.rolling(period).std()
    return pd.DataFrame({
        "bb_upper": middle + std_dev * std,
        "bb_middle": middle,
        "bb_lower": middle - std_dev * std,
        "bb_width": 2 * std_dev * std,
    })


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0), index=df.index)
    atr_val = atr(df, period)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_val
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_val
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return pd.DataFrame({"adx": adx_val, "plus_di": plus_di, "minus_di": minus_di})


def ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52, displacement: int = 26) -> pd.DataFrame:
    def mid(h, l, n):
        return (h.rolling(n).max() + l.rolling(n).min()) / 2
    tenkan_sen = mid(df["high"], df["low"], tenkan)
    kijun_sen = mid(df["high"], df["low"], kijun)
    senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(displacement)
    senkou_span_b = mid(df["high"], df["low"], senkou_b).shift(displacement)
    chikou_span = df["close"].shift(-displacement)
    return pd.DataFrame({
        "tenkan": tenkan_sen,
        "kijun": kijun_sen,
        "senkou_a": senkou_span_a,
        "senkou_b": senkou_span_b,
        "chikou": chikou_span,
    })


def vpa_signal(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    out = pd.Series("Normal", index=df.index, dtype=object)
    vol_ma = df["volume"].rolling(lookback).mean()
    body = (df["close"] - df["open"]).abs()
    body_ma = body.rolling(lookback).mean()
    range_ = df["high"] - df["low"]
    close_pos = (df["close"] - df["low"]) / range_.replace(0, np.nan)
    is_up = df["close"] > df["open"]
    vol_high = df["volume"] > 1.5 * vol_ma
    vol_low = df["volume"] < 0.7 * vol_ma
    body_large = body > 1.2 * body_ma
    sos = vol_high & is_up & body_large & (close_pos > 0.7)
    out[sos] = "SOS"
    sow = vol_high & (~is_up) & body_large & (close_pos < 0.3)
    out[sow] = "SOW"
    no_demand = vol_low & is_up & ~body_large
    out[no_demand] = "NoDemand"
    no_supply = vol_low & (~is_up) & ~body_large
    out[no_supply] = "NoSupply"
    upthrust = vol_high & (close_pos < 0.3) & (df["high"] > df["high"].shift(1))
    out[upthrust & ~sos & ~sow] = "UpThrust"
    spring = vol_high & (close_pos > 0.7) & (df["low"] < df["low"].shift(1))
    out[spring & ~sos & ~sow] = "Spring"
    return out


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Thieu columns: {missing}")
    df["ma20"] = sma(df["close"], 20)
    df["ma50"] = sma(df["close"], 50)
    df["ma200"] = sma(df["close"], 200)
    df["rsi"] = rsi(df["close"], 14)
    df = df.join(macd(df["close"]))
    df["mfi"] = mfi(df, 14)
    df = df.join(bollinger_bands(df["close"], 20, 2.0))
    df["atr"] = atr(df, 14)
    df = df.join(adx(df, 14))
    df = df.join(ichimoku(df))
    df["vol_ma20"] = sma(df["volume"], 20)
    df["vol_ratio"] = df["volume"] / df["vol_ma20"]
    df["vpa"] = vpa_signal(df)
    return df


# ============================================================
# Screener helpers
# ============================================================

def is_above_ma(df: pd.DataFrame, ma_period: int = 20) -> bool:
    if len(df) < ma_period:
        return False
    last_close = df["close"].iloc[-1]
    last_ma = sma(df["close"], ma_period).iloc[-1]
    return bool(last_close > last_ma) if pd.notna(last_ma) else False


def is_breaking_ma(df: pd.DataFrame, ma_period: int = 20) -> bool:
    if len(df) < ma_period + 1:
        return False
    ma_series = sma(df["close"], ma_period)
    prev_below = df["close"].iloc[-2] <= ma_series.iloc[-2]
    now_above = df["close"].iloc[-1] > ma_series.iloc[-1]
    return bool(prev_below and now_above)


def is_squeeze(df: pd.DataFrame, period: int = 20) -> bool:
    if len(df) < 126:
        return False
    bb = bollinger_bands(df["close"], period)
    cur = bb["bb_width"].iloc[-1]
    avg = bb["bb_width"].iloc[-126:-21].mean()
    if pd.isna(cur) or pd.isna(avg) or avg == 0:
        return False
    return bool(cur < 0.5 * avg)


def is_vpa_setup(df: pd.DataFrame) -> bool:
    if len(df) < 5:
        return False
    recent = vpa_signal(df).iloc[-5:]
    return bool(("SOS" in recent.values) or ("Spring" in recent.values))


def is_strong_trend(df: pd.DataFrame) -> bool:
    if len(df) < 30:
        return False
    a = adx(df)
    last_adx = a["adx"].iloc[-1]
    last_plus = a["plus_di"].iloc[-1]
    last_minus = a["minus_di"].iloc[-1]
    if pd.isna(last_adx):
        return False
    return bool(last_adx > 25 and last_plus > last_minus)