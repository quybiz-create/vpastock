"""
Wyckoff Phase Detection - Phase 9A

Tự động phát hiện các giai đoạn Accumulation (tích lũy) và
Distribution (phân phối) theo lý thuyết Richard Wyckoff.

WYCKOFF SCHEMATIC:

ACCUMULATION (xuất hiện SAU downtrend):
  Phase A: Stopping the previous downtrend
    - PS (Preliminary Support): Hỗ trợ sơ bộ, lần đầu tiên có lực mua xuất hiện
    - SC (Selling Climax): Đỉnh điểm bán tháo, volume cao bất thường + range rộng
    - AR (Automatic Rally): Hồi phục tự động sau SC
    - ST (Secondary Test): Test lại vùng SC, volume thấp hơn → chứng tỏ sức bán cạn

  Phase B: Building the cause (tích lũy âm thầm)
    - Sideway trong Trading Range (TR) giữa AR và SC
    - Volume giảm dần, Smart money âm thầm mua

  Phase C: Test cuối cùng + Spring
    - Spring: Giá phá đáy TR rồi đảo chiều nhanh — "shake-out" yếu tay
    - Volume Spring có thể cao hoặc trung bình (Spring Test xác nhận)

  Phase D: Markup begins (giai đoạn quan trọng để vào lệnh)
    - Giá tăng dần, đóng cửa gần đỉnh ngày
    - LPS (Last Point of Support): Hỗ trợ lùi về trước khi tăng mạnh
    - SOS (Sign of Strength): Đợt tăng mạnh với volume tốt

  Phase E: Markup rõ ràng — breakout TR + uptrend

DISTRIBUTION (xuất hiện SAU uptrend, ngược lại):
  Phase A: PSY → BC → AR → ST
  Phase B: Sideway building cause
  Phase C: UTAD (Upthrust After Distribution): phá đỉnh giả rồi đảo chiều
  Phase D: Markdown begins — LPSY (Last Point of Supply)
  Phase E: Markdown rõ ràng — break TR xuống

CÁCH PHÁT HIỆN THUẬT TOÁN:
1. Detect Trading Range (TR): vùng giá sideway 30-60 bars
2. Identify pre-trend: trước TR là uptrend hay downtrend?
3. Tìm climax bars: volume > 1.8 × MA20, range > 1.5 × ATR14
4. Định nghĩa key levels: TR high, TR low, mid
5. Tìm Spring / UTAD: phá break-out giả rồi đảo chiều
6. Xác định Phase hiện tại theo timeline + characteristics
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import math
from loguru import logger


# ============================================================
# Data structures
# ============================================================
@dataclass
class WyckoffEvent:
    """1 sự kiện key trong schematic Wyckoff."""
    index: int
    bar_time: Any
    price: float
    type: str   # PS, SC, AR, ST, Spring, UTAD, LPS, LPSY, SOS, ...
    desc: str
    confidence: float = 0.5


@dataclass
class WyckoffAnalysis:
    """Kết quả phân tích Wyckoff."""
    setup: str   # 'accumulation' / 'distribution' / 'none'
    phase: str   # 'A' / 'B' / 'C' / 'D' / 'E' / 'none'
    confidence: float   # 0..1
    trading_range: Optional[Dict[str, Any]]   # {high, low, mid, start_idx, end_idx}
    events: List[WyckoffEvent]
    suggestion: str   # gợi ý giao dịch
    description: str


# ============================================================
# Helpers
# ============================================================
def _atr(bars: List[Dict[str, float]], period: int = 14) -> List[float]:
    """ATR calculation (Wilder smoothing)."""
    if len(bars) < 2:
        return [0.0] * len(bars)
    trs = [0.0]
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    out = [0.0] * len(bars)
    if len(bars) < period:
        return out
    out[period - 1] = sum(trs[1:period]) / (period - 1)
    for i in range(period, len(bars)):
        out[i] = (out[i - 1] * (period - 1) + trs[i]) / period
    return out


def _sma(vals: List[float], period: int) -> List[Optional[float]]:
    """Simple Moving Average."""
    out: List[Optional[float]] = [None] * len(vals)
    if len(vals) < period:
        return out
    s = sum(vals[:period])
    out[period - 1] = s / period
    for i in range(period, len(vals)):
        s += vals[i] - vals[i - period]
        out[i] = s / period
    return out


def _slope(vals: List[float], window: int = 20) -> float:
    """Slope đơn giản: % change từ start tới end của window cuối."""
    if len(vals) < window or vals[-window] <= 0:
        return 0.0
    return (vals[-1] - vals[-window]) / vals[-window] * 100


def _find_trading_range(
    bars: List[Dict[str, float]],
    lookback: int = 80,
    min_bars: int = 25,
    max_range_pct: float = 18.0,
    end_back: int = 30,
) -> Optional[Dict[str, Any]]:
    """Tìm Trading Range (TR) gần nhất.

    Cho phép TR kết thúc trong [n-end_back ... n-1] để bắt được case
    đã breakout Phase E (giá đã ra khỏi TR cũ).
    """
    n = len(bars)
    if n < min_bars:
        return None
    best: Optional[Dict[str, Any]] = None
    # Thử nhiều end_idx (từ n-1 lùi về tối đa end_back bars)
    for end in range(n - 1, max(min_bars - 1, n - 1 - end_back), -1):
        for start in range(max(0, end - lookback), end - min_bars + 1):
            window = bars[start:end + 1]
            highs = [b["high"] for b in window]
            lows = [b["low"] for b in window]
            hi = max(highs)
            lo = min(lows)
            mid = (hi + lo) / 2
            if mid <= 0:
                continue
            range_pct = (hi - lo) / mid * 100
            if range_pct <= max_range_pct:
                candidate = {
                    "start_idx": start,
                    "end_idx": end,
                    "high": hi,
                    "low": lo,
                    "mid": mid,
                    "range_pct": range_pct,
                    "bars_count": end - start + 1,
                }
                # Ưu tiên TR DÀI hơn + GẦN cuối hơn
                # Score = bars_count - (n-1 - end) * 0.5 (penalize TR xa cuối)
                score = candidate["bars_count"] - (n - 1 - end) * 0.5
                candidate["_score"] = score
                if best is None or score > best.get("_score", 0):
                    best = candidate
    if best:
        best.pop("_score", None)
    return best


def _classify_pre_trend(bars: List[Dict[str, float]], tr_start: int, lookback: int = 60) -> str:
    """Phân loại xu hướng TRƯỚC khi vào Trading Range.

    Returns 'up' / 'down' / 'sideway'
    """
    start = max(0, tr_start - lookback)
    if tr_start - start < 15:
        return "sideway"
    pre = bars[start:tr_start]
    closes = [b["close"] for b in pre]
    if len(closes) < 10:
        return "sideway"
    pct = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] > 0 else 0
    if pct > 12:
        return "up"
    if pct < -12:
        return "down"
    return "sideway"


def _find_climax(
    bars: List[Dict[str, float]],
    tr_start: int,
    direction: str,
    vol_ma: List[Optional[float]],
    atr: List[float],
    vol_threshold: float = 1.8,
    range_threshold: float = 1.4,
) -> Optional[int]:
    """Tìm climax bar (SC / BC) trong vùng quanh tr_start.

    direction='sell' → tìm bar giảm mạnh + volume cao (SC)
    direction='buy'  → tìm bar tăng mạnh + volume cao (BC)
    """
    # Tìm trong khoảng [tr_start-5, tr_start+10] (gần đầu TR)
    n = len(bars)
    lo_search = max(0, tr_start - 5)
    hi_search = min(n - 1, tr_start + 10)
    
    best_idx = None
    best_score = 0.0
    for i in range(lo_search, hi_search + 1):
        b = bars[i]
        vol = b.get("volume", 0) or 0
        vol_ma_i = vol_ma[i] if i < len(vol_ma) and vol_ma[i] else 1
        atr_i = atr[i] if i < len(atr) and atr[i] > 0 else 1
        bar_range = b["high"] - b["low"]
        vol_ratio = vol / vol_ma_i if vol_ma_i > 0 else 0
        range_ratio = bar_range / atr_i if atr_i > 0 else 0
        
        # Climax: vol cao + range rộng
        if vol_ratio < vol_threshold or range_ratio < range_threshold:
            continue
        
        # Direction check
        if direction == "sell":
            # SC: nến giảm mạnh — close < open hoặc close gần low
            if b["close"] >= b["open"]:
                continue
            close_pos = (b["close"] - b["low"]) / bar_range if bar_range > 0 else 0.5
            if close_pos > 0.4:   # đóng cửa không gần low → không phải SC mạnh
                continue
        else:   # buy
            if b["close"] <= b["open"]:
                continue
            close_pos = (b["close"] - b["low"]) / bar_range if bar_range > 0 else 0.5
            if close_pos < 0.6:
                continue
        
        score = vol_ratio * range_ratio
        if score > best_score:
            best_score = score
            best_idx = i
    
    return best_idx


def _find_auto_rally(
    bars: List[Dict[str, float]], sc_idx: int, direction: str, max_look: int = 15
) -> Optional[int]:
    """Tìm AR (Automatic Rally/Reaction) sau climax bar."""
    n = len(bars)
    end = min(n - 1, sc_idx + max_look)
    if direction == "up":   # Accumulation - tìm peak rally
        peak_idx, peak_val = sc_idx, bars[sc_idx]["high"]
        for i in range(sc_idx + 1, end + 1):
            if bars[i]["high"] > peak_val:
                peak_val = bars[i]["high"]
                peak_idx = i
        if peak_idx == sc_idx:
            return None
        return peak_idx
    else:   # Distribution - tìm trough reaction
        trough_idx, trough_val = sc_idx, bars[sc_idx]["low"]
        for i in range(sc_idx + 1, end + 1):
            if bars[i]["low"] < trough_val:
                trough_val = bars[i]["low"]
                trough_idx = i
        if trough_idx == sc_idx:
            return None
        return trough_idx


def _find_spring(
    bars: List[Dict[str, float]],
    tr: Dict[str, Any],
    vol_ma: List[Optional[float]],
) -> Optional[int]:
    """Tìm Spring trong TR — bar phá thủng TR low rồi đóng cửa quay lại trên TR low.

    Spring = "shake-out" cuối: phá đáy giả để dụ short, rồi đảo chiều tăng.
    """
    start = tr["start_idx"] + max(15, (tr["end_idx"] - tr["start_idx"]) // 3)
    end = tr["end_idx"]
    tr_low = tr["low"]
    
    candidates = []
    for i in range(start, end + 1):
        b = bars[i]
        # Phá low trong ngày nhưng đóng cửa trên TR low
        if b["low"] < tr_low * 0.99 and b["close"] >= tr_low:
            candidates.append((i, b["low"]))
    
    if not candidates:
        return None
    # Lấy spring sâu nhất (low thấp nhất)
    candidates.sort(key=lambda x: x[1])
    return candidates[0][0]


def _find_utad(
    bars: List[Dict[str, float]],
    tr: Dict[str, Any],
) -> Optional[int]:
    """UTAD = Upthrust After Distribution: phá đỉnh giả rồi đảo chiều giảm."""
    start = tr["start_idx"] + max(15, (tr["end_idx"] - tr["start_idx"]) // 3)
    end = tr["end_idx"]
    tr_high = tr["high"]
    
    candidates = []
    for i in range(start, end + 1):
        b = bars[i]
        if b["high"] > tr_high * 1.01 and b["close"] <= tr_high:
            candidates.append((i, b["high"]))
    
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[1])
    return candidates[0][0]


def _classify_phase(
    setup: str,
    tr: Dict[str, Any],
    spring_idx: Optional[int],
    utad_idx: Optional[int],
    last_idx: int,
    bars: List[Dict[str, float]],
) -> Tuple[str, float, str]:
    """Phân loại Phase A/B/C/D/E hiện tại + confidence + suggestion."""
    tr_high = tr["high"]
    tr_low = tr["low"]
    tr_mid = tr["mid"]
    last_close = bars[last_idx]["close"]
    
    if setup == "accumulation":
        if last_close > tr_high * 1.02:
            return ("E", 0.75, "Markup rõ ràng — giá đã phá kháng cự TR, xu hướng tăng. Có thể cân nhắc mua khi pullback về TR high (nay là hỗ trợ).")
        if spring_idx is not None and last_idx - spring_idx <= 30:
            if last_close > tr_mid:
                return ("D", 0.80, "Markup begins — giá tăng sau Spring, đang ở giai đoạn dễ kiếm lợi nhuận nhất. Cân nhắc MUA tại LPS (pullback nhẹ).")
            else:
                return ("C", 0.70, "Phase C — Spring vừa xảy ra, đang test lại. Chờ xác nhận trước khi mua.")
        # Chưa thấy Spring rõ — Phase B
        bars_in_tr = last_idx - tr["start_idx"]
        if bars_in_tr < 12:
            return ("A", 0.55, "Phase A — Đang trong giai đoạn dừng đà giảm. Chưa nên mua, cần thêm tín hiệu.")
        return ("B", 0.60, "Phase B — Tích lũy âm thầm. Chờ Spring (phá đáy giả) hoặc breakout để xác nhận. Chưa vào lệnh.")
    
    elif setup == "distribution":
        if last_close < tr_low * 0.98:
            return ("E", 0.75, "Markdown rõ ràng — giá đã phá hỗ trợ TR, xu hướng giảm. Tránh mua, có thể short nếu rally về TR low (nay là kháng cự).")
        if utad_idx is not None and last_idx - utad_idx <= 30:
            if last_close < tr_mid:
                return ("D", 0.80, "Markdown begins — giá giảm sau UTAD, dễ thua lỗ nếu giữ. Cân nhắc CHỐT LỜI / cắt lỗ tại LPSY (pullback nhẹ).")
            else:
                return ("C", 0.70, "Phase C — UTAD vừa xảy ra, đang test lại. Cảnh báo: có thể chuyển sang downtrend.")
        bars_in_tr = last_idx - tr["start_idx"]
        if bars_in_tr < 12:
            return ("A", 0.55, "Phase A — Đang trong giai đoạn dừng đà tăng. Theo dõi, chưa cắt lỗ.")
        return ("B", 0.60, "Phase B — Phân phối âm thầm. Cảnh báo: smart money có thể đang xả. Giảm vị thế nếu lãi nhiều.")
    
    return ("none", 0.3, "Không xác định được setup Wyckoff rõ ràng. Thị trường có thể đang trending hoặc chưa hình thành TR.")


# ============================================================
# Main entry
# ============================================================
def analyze_wyckoff(bars: List[Dict[str, Any]], period: int = 200) -> Dict[str, Any]:
    """Phân tích Wyckoff trên N bars cuối.

    Args:
        bars: List of OHLCV dict {time, open, high, low, close, volume}
        period: Số bars phân tích (default 200)

    Returns:
        dict {
            setup, phase, confidence, trading_range, events, suggestion, description
        }
    """
    if not bars or len(bars) < 50:
        return {
            "setup": "none",
            "phase": "none",
            "confidence": 0.0,
            "trading_range": None,
            "events": [],
            "suggestion": "Không đủ dữ liệu (cần ít nhất 50 bars).",
            "description": "",
        }
    
    # Lấy N bars cuối
    bars = bars[-period:]
    n = len(bars)
    
    # Indicators
    volumes = [float(b.get("volume", 0) or 0) for b in bars]
    closes = [float(b["close"]) for b in bars]
    atr14 = _atr(bars, 14)
    vol_ma20 = _sma(volumes, 20)
    
    # 1. Tìm Trading Range
    tr = _find_trading_range(bars, lookback=80, min_bars=25)
    if not tr:
        return {
            "setup": "none",
            "phase": "none",
            "confidence": 0.2,
            "trading_range": None,
            "events": [],
            "suggestion": "Chưa hình thành Trading Range rõ ràng — thị trường có thể đang trending mạnh. Không phù hợp phân tích Wyckoff lúc này.",
            "description": "Wyckoff cần vùng sideway để phân tích. Chờ thị trường tích lũy/phân phối.",
        }
    
    # 2. Phân loại pre-trend → setup
    pre_trend = _classify_pre_trend(bars, tr["start_idx"], lookback=60)
    if pre_trend == "down":
        setup = "accumulation"
    elif pre_trend == "up":
        setup = "distribution"
    else:
        # Sideway dài — có thể là re-accumulation
        setup = "accumulation" if closes[-1] >= tr["mid"] else "distribution"
    
    events: List[WyckoffEvent] = []
    
    # 3. Tìm climax
    direction = "sell" if setup == "accumulation" else "buy"
    climax_idx = _find_climax(bars, tr["start_idx"], direction, vol_ma20, atr14)
    if climax_idx is not None:
        b = bars[climax_idx]
        type_label = "SC" if setup == "accumulation" else "BC"
        events.append(WyckoffEvent(
            index=climax_idx,
            bar_time=b.get("time"),
            price=b["low"] if setup == "accumulation" else b["high"],
            type=type_label,
            desc=("Selling Climax — đỉnh điểm bán tháo" if setup == "accumulation"
                  else "Buying Climax — đỉnh điểm mua đuổi"),
            confidence=0.7,
        ))
    
    # 4. Tìm AR
    if climax_idx is not None:
        ar_dir = "up" if setup == "accumulation" else "down"
        ar_idx = _find_auto_rally(bars, climax_idx, ar_dir)
        if ar_idx is not None:
            b = bars[ar_idx]
            events.append(WyckoffEvent(
                index=ar_idx,
                bar_time=b.get("time"),
                price=b["high"] if setup == "accumulation" else b["low"],
                type="AR",
                desc=("Automatic Rally — hồi phục tự động sau SC" if setup == "accumulation"
                      else "Automatic Reaction — phản ứng tự động sau BC"),
                confidence=0.65,
            ))
    
    # 5. Spring / UTAD
    spring_idx = None
    utad_idx = None
    if setup == "accumulation":
        spring_idx = _find_spring(bars, tr, vol_ma20)
        if spring_idx is not None:
            b = bars[spring_idx]
            events.append(WyckoffEvent(
                index=spring_idx,
                bar_time=b.get("time"),
                price=b["low"],
                type="Spring",
                desc="Spring — Phá đáy TR rồi đảo chiều (shake-out yếu tay)",
                confidence=0.85,
            ))
    else:
        utad_idx = _find_utad(bars, tr)
        if utad_idx is not None:
            b = bars[utad_idx]
            events.append(WyckoffEvent(
                index=utad_idx,
                bar_time=b.get("time"),
                price=b["high"],
                type="UTAD",
                desc="UTAD — Phá đỉnh TR giả rồi đảo chiều giảm",
                confidence=0.85,
            ))
    
    # 6. Phase classification
    phase, confidence, suggestion = _classify_phase(
        setup, tr, spring_idx, utad_idx, n - 1, bars
    )
    
    description = (
        f"Tích lũy" if setup == "accumulation" else "Phân phối"
    ) + f" - Phase {phase}. Trading Range từ bar {tr['start_idx']} đến {tr['end_idx']} "\
        f"({tr['bars_count']} bars), biên độ {tr['range_pct']:.1f}%."
    
    return {
        "setup": setup,
        "phase": phase,
        "confidence": round(confidence, 2),
        "trading_range": {
            "high": round(tr["high"], 2),
            "low": round(tr["low"], 2),
            "mid": round(tr["mid"], 2),
            "start_idx": tr["start_idx"],
            "end_idx": tr["end_idx"],
            "bars_count": tr["bars_count"],
            "range_pct": round(tr["range_pct"], 2),
        },
        "events": [
            {
                "index": e.index,
                "time": e.bar_time,
                "price": round(e.price, 2),
                "type": e.type,
                "desc": e.desc,
                "confidence": round(e.confidence, 2),
            }
            for e in events
        ],
        "suggestion": suggestion,
        "description": description,
        "pre_trend": pre_trend,
    }


# Standalone test với data mock
if __name__ == "__main__":
    import json
    import random
    random.seed(42)
    
    # Tạo mock data: downtrend → accumulation → markup
    bars = []
    price = 100.0
    # Downtrend 40 bars
    for i in range(40):
        price *= (1 + random.uniform(-0.025, 0.005))
        h = price * (1 + random.uniform(0, 0.015))
        l = price * (1 - random.uniform(0, 0.015))
        bars.append({"time": i, "open": price, "high": h, "low": l, "close": price, "volume": 1000000 + random.randint(-200000, 500000)})
    
    # Selling climax
    price *= 0.92
    bars.append({"time": 40, "open": price * 1.05, "high": price * 1.05, "low": price * 0.95, "close": price * 0.97, "volume": 4000000})
    # AR
    price *= 1.06
    bars.append({"time": 41, "open": price * 0.96, "high": price * 1.02, "low": price * 0.96, "close": price, "volume": 1500000})
    # TR sideway 40 bars
    tr_mid = price
    for i in range(42, 80):
        delta = random.uniform(-0.04, 0.04)
        p = tr_mid * (1 + delta)
        bars.append({"time": i, "open": p, "high": p * 1.015, "low": p * 0.985, "close": p, "volume": 1000000 + random.randint(-300000, 200000)})
    # Spring
    bars.append({"time": 80, "open": tr_mid * 0.97, "high": tr_mid * 0.98, "low": tr_mid * 0.93, "close": tr_mid * 0.97, "volume": 2500000})
    # Markup
    for i in range(81, 100):
        tr_mid *= 1.012
        bars.append({"time": i, "open": tr_mid * 0.99, "high": tr_mid * 1.015, "low": tr_mid * 0.99, "close": tr_mid, "volume": 1500000})
    
    result = analyze_wyckoff(bars, period=200)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
