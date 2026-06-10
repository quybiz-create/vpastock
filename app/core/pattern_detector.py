"""
Phase 15A: Candlestick & Price Action Patterns Auto-Detect

Detect 20+ patterns từ OHLCV DataFrame:

REVERSAL BULLISH (đáy):
  - Hammer / Pin Bar Bullish
  - Inverted Hammer
  - Bullish Engulfing
  - Piercing Line
  - Morning Star
  - Three White Soldiers
  - Bullish Harami

REVERSAL BEARISH (đỉnh):
  - Shooting Star / Pin Bar Bearish
  - Hanging Man
  - Bearish Engulfing
  - Dark Cloud Cover
  - Evening Star
  - Three Black Crows
  - Bearish Harami

INDECISION / TRANSITION:
  - Doji (standard, dragonfly, gravestone, long-legged)
  - Spinning Top

PRICE ACTION (advanced):
  - Inside Bar
  - Outside Bar (Engulfing zone)
  - Marubozu

Mỗi pattern trả về:
- name (tên TV/EN)
- name_vi (tên tiếng Việt)
- direction: 'bullish' | 'bearish' | 'neutral'
- type: 'reversal' | 'continuation' | 'indecision'
- date: ngày phát hiện
- reliability: 0-100 (độ tin cậy có context+volume)
- description: giải thích vietsub
- context: 'uptrend' | 'downtrend' | 'sideways'
- volume_confirmed: bool
"""
from __future__ import annotations
import math
from typing import Dict, Any, List, Optional
import pandas as pd


# ============================================================
# HELPERS
# ============================================================

def _body(row) -> float:
    """Độ lớn body |close - open|"""
    return abs(row["close"] - row["open"])


def _upper_shadow(row) -> float:
    """Bóng trên = high - max(open, close)"""
    return row["high"] - max(row["open"], row["close"])


def _lower_shadow(row) -> float:
    """Bóng dưới = min(open, close) - low"""
    return min(row["open"], row["close"]) - row["low"]


def _total_range(row) -> float:
    """Toàn bộ range high - low"""
    return row["high"] - row["low"]


def _is_bullish(row) -> bool:
    """Nến xanh (tăng)"""
    return row["close"] > row["open"]


def _is_bearish(row) -> bool:
    """Nến đỏ (giảm)"""
    return row["close"] < row["open"]


def _avg_body(df: pd.DataFrame, lookback: int = 10, idx: int = -1) -> float:
    """Average body của N nến gần nhất (trừ nến hiện tại)"""
    end = idx if idx >= 0 else len(df) + idx
    start = max(0, end - lookback)
    if start >= end:
        return 0.0
    bodies = [_body(df.iloc[i]) for i in range(start, end)]
    return sum(bodies) / len(bodies) if bodies else 0.0


def _trend_context(df: pd.DataFrame, idx: int, lookback: int = 10) -> str:
    """Xác định context trước nến idx: uptrend / downtrend / sideways"""
    if idx < lookback:
        return "sideways"
    closes = df["close"].iloc[idx - lookback:idx].values
    if len(closes) < 5:
        return "sideways"
    start = float(closes[0])
    end = float(closes[-1])
    if start <= 0:
        return "sideways"
    change_pct = (end - start) / start * 100
    if change_pct > 3:
        return "uptrend"
    elif change_pct < -3:
        return "downtrend"
    else:
        return "sideways"


def _volume_confirm(df: pd.DataFrame, idx: int, threshold: float = 1.2) -> bool:
    """Volume của nến idx cao hơn TB 20 nến gần đây × threshold"""
    if idx < 20 or "volume" not in df.columns:
        return False
    vol_now = float(df["volume"].iloc[idx])
    vol_avg = float(df["volume"].iloc[max(0, idx - 20):idx].mean())
    return vol_avg > 0 and vol_now > vol_avg * threshold


# ============================================================
# SINGLE-CANDLE PATTERNS
# ============================================================

def detect_hammer(df: pd.DataFrame, idx: int) -> Optional[Dict[str, Any]]:
    """Hammer: nến đáy có thân nhỏ, bóng dưới dài ≥ 2× body, bóng trên rất nhỏ.
    Phải xuất hiện sau downtrend → reversal bullish."""
    row = df.iloc[idx]
    rng = _total_range(row)
    if rng <= 0:
        return None
    body = _body(row)
    low_sh = _lower_shadow(row)
    up_sh = _upper_shadow(row)
    
    if body <= 0:
        return None
    if low_sh < body * 2:
        return None
    if up_sh > body * 0.5:
        return None
    if body > rng * 0.4:   # body must be small
        return None
    
    context = _trend_context(df, idx)
    is_hanging = context == "uptrend"
    
    return {
        "name": "Hanging Man" if is_hanging else "Hammer",
        "name_vi": "Người treo cổ" if is_hanging else "Búa (Hammer)",
        "direction": "bearish" if is_hanging else "bullish",
        "type": "reversal",
        "reliability": 70 if context in ("uptrend", "downtrend") else 45,
        "description": (
            "Nến đảo chiều giảm sau xu hướng tăng. Body nhỏ, bóng dưới dài."
            if is_hanging else
            "Nến đảo chiều tăng sau xu hướng giảm. Body nhỏ ở trên, bóng dưới dài thể hiện áp lực mua đẩy giá lên."
        ),
        "context": context,
    }


def detect_shooting_star(df: pd.DataFrame, idx: int) -> Optional[Dict[str, Any]]:
    """Shooting Star: body nhỏ ở dưới, bóng trên dài ≥ 2× body, bóng dưới rất nhỏ.
    Phải sau uptrend → reversal bearish."""
    row = df.iloc[idx]
    rng = _total_range(row)
    if rng <= 0:
        return None
    body = _body(row)
    up_sh = _upper_shadow(row)
    low_sh = _lower_shadow(row)
    
    if body <= 0:
        return None
    if up_sh < body * 2:
        return None
    if low_sh > body * 0.5:
        return None
    if body > rng * 0.4:
        return None
    
    context = _trend_context(df, idx)
    is_inverted_hammer = context == "downtrend"
    
    return {
        "name": "Inverted Hammer" if is_inverted_hammer else "Shooting Star",
        "name_vi": "Búa ngược" if is_inverted_hammer else "Sao băng",
        "direction": "bullish" if is_inverted_hammer else "bearish",
        "type": "reversal",
        "reliability": 65 if context in ("uptrend", "downtrend") else 40,
        "description": (
            "Nến đảo chiều tăng sau xu hướng giảm. Body nhỏ ở dưới, bóng trên dài."
            if is_inverted_hammer else
            "Nến đảo chiều giảm sau xu hướng tăng. Bóng trên dài cho thấy áp lực bán mạnh."
        ),
        "context": context,
    }


def detect_doji(df: pd.DataFrame, idx: int) -> Optional[Dict[str, Any]]:
    """Doji: open ≈ close (body cực nhỏ ≤ 10% range)."""
    row = df.iloc[idx]
    rng = _total_range(row)
    if rng <= 0:
        return None
    body = _body(row)
    if body > rng * 0.1:
        return None
    
    up_sh = _upper_shadow(row)
    low_sh = _lower_shadow(row)
    
    # Sub-types
    if low_sh > rng * 0.65 and up_sh < rng * 0.15:
        sub_name = "Dragonfly Doji"
        sub_vi = "Doji chuồn chuồn"
        direction = "bullish"
        desc = "Doji có bóng dưới dài, có thể đảo chiều tăng nếu xuất hiện sau downtrend."
    elif up_sh > rng * 0.65 and low_sh < rng * 0.15:
        sub_name = "Gravestone Doji"
        sub_vi = "Doji bia mộ"
        direction = "bearish"
        desc = "Doji có bóng trên dài, có thể đảo chiều giảm nếu xuất hiện sau uptrend."
    elif up_sh > rng * 0.3 and low_sh > rng * 0.3:
        sub_name = "Long-Legged Doji"
        sub_vi = "Doji chân dài"
        direction = "neutral"
        desc = "Lưỡng lự cao, cả người mua và bán đều thử nhưng giá đóng tại điểm mở."
    else:
        sub_name = "Doji"
        sub_vi = "Doji thường"
        direction = "neutral"
        desc = "Lưỡng lự thị trường, có thể là tín hiệu đảo chiều khi xuất hiện sau xu hướng mạnh."
    
    context = _trend_context(df, idx)
    return {
        "name": sub_name,
        "name_vi": sub_vi,
        "direction": direction,
        "type": "indecision",
        "reliability": 55 if context in ("uptrend", "downtrend") else 35,
        "description": desc,
        "context": context,
    }


def detect_marubozu(df: pd.DataFrame, idx: int) -> Optional[Dict[str, Any]]:
    """Marubozu: body cực lớn (≥ 90% range), không có hoặc rất ít bóng."""
    row = df.iloc[idx]
    rng = _total_range(row)
    if rng <= 0:
        return None
    body = _body(row)
    up_sh = _upper_shadow(row)
    low_sh = _lower_shadow(row)
    
    if body < rng * 0.9:
        return None
    if up_sh > rng * 0.05 or low_sh > rng * 0.05:
        return None
    
    bull = _is_bullish(row)
    avg_body = _avg_body(df, lookback=10, idx=idx)
    if avg_body > 0 and body < avg_body * 1.5:
        return None
    
    return {
        "name": "Bullish Marubozu" if bull else "Bearish Marubozu",
        "name_vi": "Marubozu Tăng" if bull else "Marubozu Giảm",
        "direction": "bullish" if bull else "bearish",
        "type": "continuation",
        "reliability": 70,
        "description": (
            "Nến tăng cực mạnh, không có bóng. Phe mua hoàn toàn kiểm soát."
            if bull else
            "Nến giảm cực mạnh, không có bóng. Phe bán hoàn toàn kiểm soát."
        ),
        "context": _trend_context(df, idx),
    }


def detect_spinning_top(df: pd.DataFrame, idx: int) -> Optional[Dict[str, Any]]:
    """Spinning Top: body nhỏ, có cả bóng trên và bóng dưới gần bằng nhau."""
    row = df.iloc[idx]
    rng = _total_range(row)
    if rng <= 0:
        return None
    body = _body(row)
    up_sh = _upper_shadow(row)
    low_sh = _lower_shadow(row)
    
    if body > rng * 0.3:   # body should be small
        return None
    if up_sh < body or low_sh < body:
        return None
    # Bóng trên/dưới gần bằng nhau (cách nhau < 50%)
    if up_sh == 0 or low_sh == 0:
        return None
    ratio = max(up_sh, low_sh) / min(up_sh, low_sh)
    if ratio > 2.0:
        return None
    
    return {
        "name": "Spinning Top",
        "name_vi": "Con quay",
        "direction": "neutral",
        "type": "indecision",
        "reliability": 40,
        "description": "Lưỡng lự nhẹ, cần xác nhận từ nến kế tiếp.",
        "context": _trend_context(df, idx),
    }


def detect_pin_bar(df: pd.DataFrame, idx: int) -> Optional[Dict[str, Any]]:
    """Pin Bar (Nial Fuller): body chiếm < 30% range, 1 bóng dài chiếm ≥ 60% range,
    bóng còn lại < 15% range. Mạnh hơn Hammer/Shooting Star về tính price action."""
    row = df.iloc[idx]
    rng = _total_range(row)
    if rng <= 0:
        return None
    body = _body(row)
    up_sh = _upper_shadow(row)
    low_sh = _lower_shadow(row)
    
    if body > rng * 0.3:
        return None
    
    # Bullish Pin (bóng dưới dài)
    if low_sh >= rng * 0.6 and up_sh < rng * 0.15:
        return {
            "name": "Bullish Pin Bar",
            "name_vi": "Pin Bar Tăng",
            "direction": "bullish",
            "type": "reversal",
            "reliability": 75,
            "description": "Pin Bar đảo chiều tăng. Bóng dưới dài bị từ chối, áp lực mua mạnh.",
            "context": _trend_context(df, idx),
        }
    # Bearish Pin (bóng trên dài)
    if up_sh >= rng * 0.6 and low_sh < rng * 0.15:
        return {
            "name": "Bearish Pin Bar",
            "name_vi": "Pin Bar Giảm",
            "direction": "bearish",
            "type": "reversal",
            "reliability": 75,
            "description": "Pin Bar đảo chiều giảm. Bóng trên dài bị từ chối, áp lực bán mạnh.",
            "context": _trend_context(df, idx),
        }
    
    return None


# ============================================================
# TWO-CANDLE PATTERNS
# ============================================================

def detect_engulfing(df: pd.DataFrame, idx: int) -> Optional[Dict[str, Any]]:
    """Bullish/Bearish Engulfing: nến 2 nuốt trọn body nến 1, ngược chiều."""
    if idx < 1:
        return None
    prev = df.iloc[idx - 1]
    curr = df.iloc[idx]
    
    prev_body = _body(prev)
    curr_body = _body(curr)
    
    if prev_body <= 0 or curr_body <= 0:
        return None
    if curr_body < prev_body * 1.0:
        return None
    
    context = _trend_context(df, idx)
    
    # Bullish Engulfing: prev red, curr green, curr body engulfs prev body
    if _is_bearish(prev) and _is_bullish(curr):
        if curr["open"] <= prev["close"] and curr["close"] >= prev["open"]:
            return {
                "name": "Bullish Engulfing",
                "name_vi": "Nhấn chìm Tăng",
                "direction": "bullish",
                "type": "reversal",
                "reliability": 80 if context == "downtrend" else 50,
                "description": "Nến xanh nhấn chìm nến đỏ trước đó. Đảo chiều tăng mạnh nếu sau downtrend.",
                "context": context,
            }
    
    # Bearish Engulfing
    if _is_bullish(prev) and _is_bearish(curr):
        if curr["open"] >= prev["close"] and curr["close"] <= prev["open"]:
            return {
                "name": "Bearish Engulfing",
                "name_vi": "Nhấn chìm Giảm",
                "direction": "bearish",
                "type": "reversal",
                "reliability": 80 if context == "uptrend" else 50,
                "description": "Nến đỏ nhấn chìm nến xanh trước đó. Đảo chiều giảm mạnh nếu sau uptrend.",
                "context": context,
            }
    
    return None


def detect_harami(df: pd.DataFrame, idx: int) -> Optional[Dict[str, Any]]:
    """Harami: nến 2 có body NẰM TRONG body nến 1 (ngược lại engulfing)."""
    if idx < 1:
        return None
    prev = df.iloc[idx - 1]
    curr = df.iloc[idx]
    
    prev_body = _body(prev)
    curr_body = _body(curr)
    
    if prev_body <= 0 or curr_body <= 0:
        return None
    if curr_body > prev_body * 0.6:   # curr must be smaller
        return None
    
    context = _trend_context(df, idx)
    
    # Bullish Harami: prev red, curr green, curr body inside prev body
    if _is_bearish(prev) and _is_bullish(curr):
        if curr["open"] >= prev["close"] and curr["close"] <= prev["open"]:
            return {
                "name": "Bullish Harami",
                "name_vi": "Harami Tăng",
                "direction": "bullish",
                "type": "reversal",
                "reliability": 65 if context == "downtrend" else 35,
                "description": "Nến xanh nhỏ nằm trong body nến đỏ lớn. Đảo chiều tăng tiềm năng.",
                "context": context,
            }
    
    # Bearish Harami
    if _is_bullish(prev) and _is_bearish(curr):
        if curr["open"] <= prev["close"] and curr["close"] >= prev["open"]:
            return {
                "name": "Bearish Harami",
                "name_vi": "Harami Giảm",
                "direction": "bearish",
                "type": "reversal",
                "reliability": 65 if context == "uptrend" else 35,
                "description": "Nến đỏ nhỏ nằm trong body nến xanh lớn. Đảo chiều giảm tiềm năng.",
                "context": context,
            }
    
    return None


def detect_piercing_dark_cloud(df: pd.DataFrame, idx: int) -> Optional[Dict[str, Any]]:
    """Piercing Line / Dark Cloud Cover: nến 2 mở gap rồi đóng quá midpoint nến 1."""
    if idx < 1:
        return None
    prev = df.iloc[idx - 1]
    curr = df.iloc[idx]
    
    prev_body = _body(prev)
    if prev_body <= 0:
        return None
    
    midpoint = (prev["open"] + prev["close"]) / 2
    context = _trend_context(df, idx)
    
    # Piercing Line: prev red, curr green opens below prev low, closes above midpoint
    if _is_bearish(prev) and _is_bullish(curr):
        if curr["open"] < prev["low"] and curr["close"] > midpoint and curr["close"] < prev["open"]:
            return {
                "name": "Piercing Line",
                "name_vi": "Đường xuyên",
                "direction": "bullish",
                "type": "reversal",
                "reliability": 70 if context == "downtrend" else 40,
                "description": "Nến xanh mở gap xuống nhưng đóng trên midpoint nến đỏ trước. Đảo chiều tăng.",
                "context": context,
            }
    
    # Dark Cloud Cover: prev green, curr red opens above prev high, closes below midpoint
    if _is_bullish(prev) and _is_bearish(curr):
        if curr["open"] > prev["high"] and curr["close"] < midpoint and curr["close"] > prev["open"]:
            return {
                "name": "Dark Cloud Cover",
                "name_vi": "Mây đen che phủ",
                "direction": "bearish",
                "type": "reversal",
                "reliability": 70 if context == "uptrend" else 40,
                "description": "Nến đỏ mở gap lên nhưng đóng dưới midpoint nến xanh trước. Đảo chiều giảm.",
                "context": context,
            }
    
    return None


def detect_inside_bar(df: pd.DataFrame, idx: int) -> Optional[Dict[str, Any]]:
    """Inside Bar: high của nến 2 < high nến 1 VÀ low nến 2 > low nến 1."""
    if idx < 1:
        return None
    prev = df.iloc[idx - 1]
    curr = df.iloc[idx]
    
    if curr["high"] < prev["high"] and curr["low"] > prev["low"]:
        return {
            "name": "Inside Bar",
            "name_vi": "Nến trong",
            "direction": "neutral",
            "type": "continuation",
            "reliability": 55,
            "description": "Nến mới nằm hoàn toàn trong range nến trước. Báo hiệu nén năng lượng, breakout sắp tới.",
            "context": _trend_context(df, idx),
        }
    
    return None


def detect_outside_bar(df: pd.DataFrame, idx: int) -> Optional[Dict[str, Any]]:
    """Outside Bar: high nến 2 > high nến 1 VÀ low nến 2 < low nến 1.
    Mạnh hơn engulfing vì cả range bị engulf."""
    if idx < 1:
        return None
    prev = df.iloc[idx - 1]
    curr = df.iloc[idx]
    
    if curr["high"] > prev["high"] and curr["low"] < prev["low"]:
        bull = _is_bullish(curr)
        context = _trend_context(df, idx)
        return {
            "name": "Bullish Outside Bar" if bull else "Bearish Outside Bar",
            "name_vi": "Outside Bar Tăng" if bull else "Outside Bar Giảm",
            "direction": "bullish" if bull else "bearish",
            "type": "reversal",
            "reliability": 75,
            "description": (
                "Nến xanh có range nuốt trọn nến trước. Tín hiệu đảo chiều tăng cực mạnh."
                if bull else
                "Nến đỏ có range nuốt trọn nến trước. Tín hiệu đảo chiều giảm cực mạnh."
            ),
            "context": context,
        }
    
    return None


# ============================================================
# THREE-CANDLE PATTERNS
# ============================================================

def detect_morning_evening_star(df: pd.DataFrame, idx: int) -> Optional[Dict[str, Any]]:
    """Morning Star (3 nến đáy đảo chiều tăng) / Evening Star (3 nến đỉnh đảo chiều giảm).
    
    Morning Star:
      - Nến 1: đỏ dài (continuation downtrend)
      - Nến 2: body nhỏ (doji/spinning) gap xuống
      - Nến 3: xanh dài, đóng cao hơn midpoint nến 1
    
    Evening Star: ngược lại.
    """
    if idx < 2:
        return None
    c1 = df.iloc[idx - 2]
    c2 = df.iloc[idx - 1]
    c3 = df.iloc[idx]
    
    b1 = _body(c1)
    b2 = _body(c2)
    b3 = _body(c3)
    
    if b1 <= 0 or b3 <= 0:
        return None
    if b2 > b1 * 0.4:   # middle candle must be small
        return None
    if b3 < b1 * 0.6:   # third candle must be substantial
        return None
    
    mid1 = (c1["open"] + c1["close"]) / 2
    context = _trend_context(df, idx - 2)   # context BEFORE the pattern
    
    # Morning Star
    if _is_bearish(c1) and _is_bullish(c3):
        if max(c2["open"], c2["close"]) < c1["close"] and c3["close"] > mid1:
            return {
                "name": "Morning Star",
                "name_vi": "Sao Mai",
                "direction": "bullish",
                "type": "reversal",
                "reliability": 85 if context == "downtrend" else 55,
                "description": "Mô hình 3 nến đảo chiều tăng rất mạnh: đỏ dài → doji → xanh dài.",
                "context": context,
            }
    
    # Evening Star
    if _is_bullish(c1) and _is_bearish(c3):
        if min(c2["open"], c2["close"]) > c1["close"] and c3["close"] < mid1:
            return {
                "name": "Evening Star",
                "name_vi": "Sao Hôm",
                "direction": "bearish",
                "type": "reversal",
                "reliability": 85 if context == "uptrend" else 55,
                "description": "Mô hình 3 nến đảo chiều giảm rất mạnh: xanh dài → doji → đỏ dài.",
                "context": context,
            }
    
    return None


def detect_three_soldiers_crows(df: pd.DataFrame, idx: int) -> Optional[Dict[str, Any]]:
    """Three White Soldiers / Three Black Crows: 3 nến cùng chiều liên tiếp, mỗi nến đóng
    gần đỉnh/đáy của range, mỗi nến mở trong body nến trước."""
    if idx < 2:
        return None
    c1 = df.iloc[idx - 2]
    c2 = df.iloc[idx - 1]
    c3 = df.iloc[idx]
    
    # Bodies must all be substantial
    for c in (c1, c2, c3):
        if _body(c) <= 0:
            return None
    
    avg_body = _avg_body(df, lookback=10, idx=idx - 2)
    if avg_body <= 0:
        return None
    
    # Each body must be at least average
    if not all(_body(c) >= avg_body * 0.7 for c in (c1, c2, c3)):
        return None
    
    context = _trend_context(df, idx - 2)
    
    # Three White Soldiers
    if all(_is_bullish(c) for c in (c1, c2, c3)):
        # Each open within previous body
        if c1["open"] < c2["open"] < c3["open"] and c1["close"] < c2["close"] < c3["close"]:
            if c2["open"] >= c1["open"] and c2["open"] <= c1["close"]:
                if c3["open"] >= c2["open"] and c3["open"] <= c2["close"]:
                    return {
                        "name": "Three White Soldiers",
                        "name_vi": "Ba chàng lính trắng",
                        "direction": "bullish",
                        "type": "reversal",
                        "reliability": 80 if context == "downtrend" else 65,
                        "description": "3 nến xanh liên tiếp, mỗi nến đóng cao hơn nến trước. Sức mua áp đảo.",
                        "context": context,
                    }
    
    # Three Black Crows
    if all(_is_bearish(c) for c in (c1, c2, c3)):
        if c1["open"] > c2["open"] > c3["open"] and c1["close"] > c2["close"] > c3["close"]:
            if c2["open"] <= c1["open"] and c2["open"] >= c1["close"]:
                if c3["open"] <= c2["open"] and c3["open"] >= c2["close"]:
                    return {
                        "name": "Three Black Crows",
                        "name_vi": "Ba con quạ đen",
                        "direction": "bearish",
                        "type": "reversal",
                        "reliability": 80 if context == "uptrend" else 65,
                        "description": "3 nến đỏ liên tiếp, mỗi nến đóng thấp hơn nến trước. Sức bán áp đảo.",
                        "context": context,
                    }
    
    return None


# ============================================================
# MAIN: DETECT ALL PATTERNS
# ============================================================

# Registered detectors: each returns Optional[Dict] for given idx
_SINGLE_CANDLE_DETECTORS = [
    detect_hammer,
    detect_shooting_star,
    detect_pin_bar,
    detect_doji,
    detect_marubozu,
    detect_spinning_top,
]

_TWO_CANDLE_DETECTORS = [
    detect_engulfing,
    detect_harami,
    detect_piercing_dark_cloud,
    detect_inside_bar,
    detect_outside_bar,
]

_THREE_CANDLE_DETECTORS = [
    detect_morning_evening_star,
    detect_three_soldiers_crows,
]


def detect_all_patterns(df: pd.DataFrame, lookback_days: int = 30) -> List[Dict[str, Any]]:
    """Scan toàn bộ N nến gần nhất, return list patterns tìm được.
    
    df: DataFrame có cột open, high, low, close, volume (index là ngày)
    lookback_days: scan N ngày gần nhất
    
    Returns: list of pattern dicts, sorted theo ngày desc (mới nhất trước)
    """
    if df is None or df.empty or len(df) < 5:
        return []
    
    # Đảm bảo sorted theo ngày tăng
    df = df.sort_index()
    
    n = len(df)
    start_idx = max(0, n - lookback_days)
    
    results: List[Dict[str, Any]] = []
    
    for idx in range(start_idx, n):
        date_str = df.index[idx].strftime("%Y-%m-%d") if hasattr(df.index[idx], "strftime") else str(df.index[idx])
        
        # 3-candle patterns FIRST (mạnh nhất, ưu tiên)
        found_3 = False
        for detector in _THREE_CANDLE_DETECTORS:
            try:
                result = detector(df, idx)
                if result:
                    result["date"] = date_str
                    result["volume_confirmed"] = _volume_confirm(df, idx)
                    if result["volume_confirmed"]:
                        result["reliability"] = min(100, result["reliability"] + 10)
                    results.append(result)
                    found_3 = True
                    break  # Chỉ lấy 1 pattern 3-nến/idx (tránh duplicate)
            except Exception:
                pass
        
        # 2-candle patterns
        found_2 = False
        for detector in _TWO_CANDLE_DETECTORS:
            try:
                result = detector(df, idx)
                if result:
                    result["date"] = date_str
                    result["volume_confirmed"] = _volume_confirm(df, idx)
                    if result["volume_confirmed"]:
                        result["reliability"] = min(100, result["reliability"] + 10)
                    results.append(result)
                    found_2 = True
                    break
            except Exception:
                pass
        
        # 1-candle patterns
        for detector in _SINGLE_CANDLE_DETECTORS:
            try:
                result = detector(df, idx)
                if result:
                    result["date"] = date_str
                    result["volume_confirmed"] = _volume_confirm(df, idx)
                    if result["volume_confirmed"]:
                        result["reliability"] = min(100, result["reliability"] + 10)
                    results.append(result)
                    break   # 1 pattern/nến là đủ
            except Exception:
                pass
    
    # Sort: ngày mới nhất trước, rồi theo reliability
    results.sort(key=lambda x: (x["date"], x["reliability"]), reverse=True)
    
    return results


def get_pattern_summary(patterns: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Tóm tắt patterns: bullish/bearish/neutral count, latest pattern, etc."""
    if not patterns:
        return {
            "total": 0,
            "bullish": 0,
            "bearish": 0,
            "neutral": 0,
            "overall": "neutral",
            "latest": None,
        }
    
    bullish = sum(1 for p in patterns if p["direction"] == "bullish")
    bearish = sum(1 for p in patterns if p["direction"] == "bearish")
    neutral = sum(1 for p in patterns if p["direction"] == "neutral")
    
    if bullish > bearish * 1.5:
        overall = "bullish"
    elif bearish > bullish * 1.5:
        overall = "bearish"
    else:
        overall = "neutral"
    
    # Latest pattern (ngày mới nhất)
    latest = patterns[0] if patterns else None
    
    return {
        "total": len(patterns),
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "overall": overall,
        "latest": latest,
    }


# Standalone test
if __name__ == "__main__":
    import pandas as pd
    from datetime import datetime, timedelta
    
    # Simulate uptrend → hammer → bullish engulfing → continue
    data = {
        "open":   [100, 102, 105, 108, 110, 109, 105, 100, 95, 97, 102, 108],
        "high":   [103, 106, 109, 112, 113, 110, 106, 101, 98, 103, 109, 112],
        "low":    [99, 101, 104, 107, 108, 105, 99, 94, 90, 96, 101, 107],
        "close":  [102, 105, 108, 110, 109, 105, 100, 95, 97, 102, 108, 111],
        "volume": [1000, 1200, 1500, 1800, 2000, 2500, 3000, 4000, 5000, 4500, 3500, 2800],
    }
    dates = [datetime.now() - timedelta(days=11-i) for i in range(12)]
    df = pd.DataFrame(data, index=pd.DatetimeIndex(dates))
    
    print("=" * 60)
    print("PATTERN DETECTION TEST")
    print("=" * 60)
    
    patterns = detect_all_patterns(df, lookback_days=15)
    print(f"\nFound {len(patterns)} patterns:\n")
    for p in patterns:
        print(f"📅 {p['date']} | {p['name_vi']} ({p['name']})")
        print(f"   → {p['direction'].upper()} | Reliability: {p['reliability']} | Context: {p['context']}")
        print(f"   {p['description']}")
        print()
    
    summary = get_pattern_summary(patterns)
    print(f"📊 SUMMARY: {summary['bullish']}↑ / {summary['bearish']}↓ / {summary['neutral']}~ → {summary['overall'].upper()}")
