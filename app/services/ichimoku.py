"""
Phase 17A: Ichimoku Cloud (Ichimoku Kinko Hyo) - v2 with Strategy
"""
from __future__ import annotations
import asyncio
import os
import math
import time as _time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from loguru import logger
import httpx


_FIREANT_BASE = "https://restv2.fireant.vn"
_CACHE: Dict[str, Any] = {}
_CACHE_TTL = 600


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _get_fireant_token() -> Optional[str]:
    return os.environ.get("FIREANT_TOKEN") or None


def _highest(values, period, idx):
    start = max(0, idx - period + 1)
    if idx < start: return None
    window = values[start:idx + 1]
    return max(window) if window else None


def _lowest(values, period, idx):
    start = max(0, idx - period + 1)
    if idx < start: return None
    window = values[start:idx + 1]
    return min(window) if window else None


def compute_ichimoku(highs, lows, closes,
                    tenkan_period=9, kijun_period=26, senkou_b_period=52, displacement=26):
    n = len(closes)
    if n < senkou_b_period + displacement:
        return {"error": f"Cần ít nhất {senkou_b_period + displacement} candles"}
    
    tenkan = [None] * n
    kijun = [None] * n
    for i in range(n):
        if i >= tenkan_period - 1:
            h = _highest(highs, tenkan_period, i)
            l = _lowest(lows, tenkan_period, i)
            if h is not None and l is not None:
                tenkan[i] = (h + l) / 2
        if i >= kijun_period - 1:
            h = _highest(highs, kijun_period, i)
            l = _lowest(lows, kijun_period, i)
            if h is not None and l is not None:
                kijun[i] = (h + l) / 2
    
    senkou_a = [None] * (n + displacement)
    senkou_b = [None] * (n + displacement)
    for i in range(n):
        if tenkan[i] is not None and kijun[i] is not None:
            senkou_a[i + displacement] = (tenkan[i] + kijun[i]) / 2
        if i >= senkou_b_period - 1:
            h = _highest(highs, senkou_b_period, i)
            l = _lowest(lows, senkou_b_period, i)
            if h is not None and l is not None:
                senkou_b[i + displacement] = (h + l) / 2
    
    chikou = [None] * n
    for i in range(n):
        if i - displacement >= 0:
            chikou[i - displacement] = closes[i]
    
    today_idx = n - 1
    cloud_a_today = senkou_a[today_idx]
    cloud_b_today = senkou_b[today_idx]
    cloud_color = "neutral"
    if cloud_a_today is not None and cloud_b_today is not None:
        if cloud_a_today > cloud_b_today: cloud_color = "bullish"
        elif cloud_a_today < cloud_b_today: cloud_color = "bearish"
    
    future_idx = n + displacement - 1
    cloud_a_future = senkou_a[future_idx] if future_idx < len(senkou_a) else None
    cloud_b_future = senkou_b[future_idx] if future_idx < len(senkou_b) else None
    cloud_color_future = "neutral"
    if cloud_a_future is not None and cloud_b_future is not None:
        if cloud_a_future > cloud_b_future: cloud_color_future = "bullish"
        elif cloud_a_future < cloud_b_future: cloud_color_future = "bearish"
    
    price = closes[today_idx]
    tenkan_today = tenkan[today_idx]
    kijun_today = kijun[today_idx]
    
    cloud_top = None
    cloud_bottom = None
    if cloud_a_today is not None and cloud_b_today is not None:
        cloud_top = max(cloud_a_today, cloud_b_today)
        cloud_bottom = min(cloud_a_today, cloud_b_today)
    
    position = "unknown"
    if cloud_top is not None and cloud_bottom is not None:
        if price > cloud_top: position = "above_cloud"
        elif price < cloud_bottom: position = "below_cloud"
        else: position = "inside_cloud"
    
    tk_cross = "neutral"
    if tenkan_today is not None and kijun_today is not None:
        if tenkan_today > kijun_today: tk_cross = "bullish"
        elif tenkan_today < kijun_today: tk_cross = "bearish"
    
    chikou_pos = "neutral"
    if today_idx - displacement >= 0:
        chikou_value = closes[today_idx]
        price_26_ago = closes[today_idx - displacement]
        if chikou_value > price_26_ago: chikou_pos = "bullish"
        elif chikou_value < price_26_ago: chikou_pos = "bearish"
    
    # Score
    score = 0
    if position == "above_cloud": score += 2
    elif position == "below_cloud": score -= 2
    if tk_cross == "bullish": score += 1
    elif tk_cross == "bearish": score -= 1
    if chikou_pos == "bullish": score += 1
    elif chikou_pos == "bearish": score -= 1
    if cloud_color_future == "bullish": score += 1
    elif cloud_color_future == "bearish": score -= 1
    
    if score >= 4:
        signal, signal_vi, signal_emoji = "strong_buy", "MUA MẠNH", "🟢🟢"
    elif score >= 2:
        signal, signal_vi, signal_emoji = "buy", "MUA", "🟢"
    elif score <= -4:
        signal, signal_vi, signal_emoji = "strong_sell", "BÁN MẠNH", "🔴🔴"
    elif score <= -2:
        signal, signal_vi, signal_emoji = "sell", "BÁN", "🔴"
    else:
        signal, signal_vi, signal_emoji = "neutral", "TRUNG TÍNH", "🟡"
    
    return {
        "tenkan": tenkan, "kijun": kijun, "senkou_a": senkou_a, "senkou_b": senkou_b, "chikou": chikou,
        "current": {
            "price": round(price, 2),
            "tenkan": round(tenkan_today, 2) if tenkan_today else None,
            "kijun": round(kijun_today, 2) if kijun_today else None,
            "cloud_a": round(cloud_a_today, 2) if cloud_a_today else None,
            "cloud_b": round(cloud_b_today, 2) if cloud_b_today else None,
            "cloud_top": round(cloud_top, 2) if cloud_top else None,
            "cloud_bottom": round(cloud_bottom, 2) if cloud_bottom else None,
            "cloud_color": cloud_color,
            "cloud_color_future": cloud_color_future,
        },
        "signal": {
            "level": signal, "level_vi": signal_vi, "emoji": signal_emoji,
            "score": score, "position": position,
            "tk_cross": tk_cross, "chikou": chikou_pos, "future_cloud": cloud_color_future,
        },
        "analysis": _build_analysis(position, tk_cross, chikou_pos, cloud_color, cloud_color_future,
                                    tenkan_today, kijun_today, price, cloud_top, cloud_bottom),
        "strategy": _build_strategy(signal, position, price, tenkan_today, kijun_today,
                                     cloud_top, cloud_bottom, cloud_color_future),
        "key_levels": _build_key_levels(position, price, tenkan_today, kijun_today, cloud_top, cloud_bottom),
    }


def _build_analysis(position, tk_cross, chikou, cloud, cloud_future, tenkan, kijun, price, c_top, c_bot):
    analysis = []
    if position == "above_cloud":
        analysis.append("✅ Giá nằm TRÊN mây Kumo → xu hướng tăng được xác nhận")
    elif position == "below_cloud":
        analysis.append("❌ Giá nằm DƯỚI mây Kumo → xu hướng giảm được xác nhận")
    elif position == "inside_cloud":
        analysis.append("⚠️ Giá nằm TRONG mây Kumo → thị trường đang lưỡng lự, chờ tín hiệu rõ")
    if tk_cross == "bullish":
        analysis.append("✅ Tenkan > Kijun (Golden Cross) → momentum ngắn hạn tích cực")
    elif tk_cross == "bearish":
        analysis.append("❌ Tenkan < Kijun (Death Cross) → momentum ngắn hạn tiêu cực")
    if chikou == "bullish":
        analysis.append("✅ Chikou Span trên giá 26 phiên trước → xác nhận xu hướng tăng")
    elif chikou == "bearish":
        analysis.append("❌ Chikou Span dưới giá 26 phiên trước → xác nhận xu hướng giảm")
    if cloud_future == "bullish":
        analysis.append("✅ Mây tương lai 26 phiên tới là MÂY XANH → triển vọng tăng")
    elif cloud_future == "bearish":
        analysis.append("❌ Mây tương lai 26 phiên tới là MÂY ĐỎ → triển vọng giảm")
    return analysis


def _build_strategy(signal, position, price, tenkan, kijun, c_top, c_bot, cloud_future):
    """Generate actionable trading strategy based on signal."""
    strategy = {"action": "", "entries": [], "stop_loss": None, "targets": [], "notes": []}
    
    if not (tenkan and kijun and c_top and c_bot):
        return strategy
    
    if signal == "strong_buy":
        # Đang ở trên mây + tất cả bullish
        strategy["action"] = "🟢 CÓ THỂ MUA"
        strategy["entries"] = [
            f"Mua ở vùng giá hiện tại ({price:.2f}) nếu chấp nhận rủi ro cao",
            f"Hoặc chờ giá pullback về Tenkan ({tenkan:.2f}) để mua an toàn hơn",
            f"Vùng mua tốt nhất: pullback về Kijun ({kijun:.2f}) - đường hỗ trợ mạnh",
        ]
        strategy["stop_loss"] = round(c_top, 2)
        strategy["targets"] = [
            round(price * 1.05, 2),
            round(price * 1.10, 2),
            round(price * 1.20, 2),
        ]
        strategy["notes"] = [
            "📊 Cắt lỗ nếu giá thủng đỉnh mây (mất xu hướng tăng)",
            "🎯 Target 5-10% là phổ biến, target 20%+ cần chờ thêm sóng",
            "⚠️ Không all-in, chia 2-3 lần mua tốt hơn",
        ]
    
    elif signal == "buy":
        strategy["action"] = "🟢 MUA THẬN TRỌNG"
        if position == "above_cloud":
            strategy["entries"] = [
                f"Chờ giá pullback về Tenkan ({tenkan:.2f}) để mua",
                f"Hoặc vào lệnh khi giá test đỉnh mây ({c_top:.2f}) và bật lên",
            ]
            strategy["stop_loss"] = round(c_top * 0.98, 2)
        else:
            strategy["entries"] = [
                f"Chờ giá vượt đỉnh mây ({c_top:.2f}) + đóng nến mạnh để xác nhận",
            ]
            strategy["stop_loss"] = round(c_bot, 2)
        strategy["targets"] = [
            round(price * 1.05, 2),
            round(price * 1.10, 2),
        ]
        strategy["notes"] = [
            "📊 Tín hiệu chưa mạnh - chỉ nên dùng 30-50% vốn",
            "🎯 Target ngắn hạn 5-10%",
        ]
    
    elif signal == "neutral":
        strategy["action"] = "🟡 ĐỨNG NGOÀI / QUAN SÁT"
        if position == "below_cloud":
            strategy["entries"] = [
                f"KHÔNG mua đuổi giá",
                f"Chờ giá vượt đáy mây ({c_bot:.2f}) → tín hiệu BUY yếu",
                f"Chờ giá vượt đỉnh mây ({c_top:.2f}) → tín hiệu STRONG BUY",
            ]
            strategy["stop_loss"] = round(kijun * 0.98, 2) if kijun else None
        elif position == "above_cloud":
            strategy["entries"] = [
                f"Theo dõi - tín hiệu chưa đủ mạnh",
                f"Chờ Chikou hoặc Future Cloud chuyển xanh để có signal BUY mạnh hơn",
            ]
            strategy["stop_loss"] = round(c_top, 2)
        else:
            strategy["entries"] = [
                "Giá đang trong mây - thị trường lưỡng lự",
                f"Chờ break ra khỏi mây (trên {c_top:.2f} hoặc dưới {c_bot:.2f}) để có hướng rõ",
            ]
        strategy["notes"] = [
            "⚠️ Đây không phải thời điểm tốt để vào lệnh mới",
            "📊 Nếu đang nắm giữ → hold + theo dõi sát",
        ]
    
    elif signal == "sell":
        strategy["action"] = "🔴 BÁN GIẢM TỶ TRỌNG"
        strategy["entries"] = [
            "Nếu đang nắm giữ → bán bớt 30-50%",
            f"Chờ rebound về Tenkan ({tenkan:.2f}) để bán hết",
            "Không mua mới, không bắt đáy",
        ]
        strategy["stop_loss"] = None
        strategy["targets"] = []
        strategy["notes"] = [
            "📉 Xu hướng đang xấu - bảo toàn vốn ưu tiên",
            f"⚠️ Nếu vượt được đỉnh mây ({c_top:.2f}) → đảo chiều, có thể hold lại",
        ]
    
    elif signal == "strong_sell":
        strategy["action"] = "🔴🔴 TRÁNH HOÀN TOÀN"
        strategy["entries"] = [
            "TUYỆT ĐỐI không bắt đáy",
            "Nếu đang nắm giữ → bán hết, dừng lỗ",
            "Quay lại quan sát khi giá vào mây hoặc TK Cross bullish",
        ]
        strategy["notes"] = [
            "🚨 Xu hướng giảm cực mạnh - đứng ngoài",
            "💡 Có thể trade short nếu có công cụ (CFD/Phái sinh)",
            f"⚠️ Chỉ xem xét lại khi giá vượt đáy mây ({c_bot:.2f})",
        ]
    
    return strategy


def _build_key_levels(position, price, tenkan, kijun, c_top, c_bot):
    """Build key support/resistance levels for trading."""
    levels = []
    if not (tenkan and kijun and c_top and c_bot):
        return levels
    
    # Order levels relative to price
    all_levels = [
        ("Tenkan-sen", tenkan, "hỗ trợ/kháng cự ngắn hạn"),
        ("Kijun-sen", kijun, "hỗ trợ/kháng cự trung hạn"),
        ("Đỉnh mây", c_top, "kháng cự/hỗ trợ mạnh"),
        ("Đáy mây", c_bot, "kháng cự/hỗ trợ mạnh"),
    ]
    
    for name, value, desc in all_levels:
        diff_pct = ((value - price) / price) * 100
        if value > price:
            level_type = "kháng cự"
            icon = "🔺"
        elif value < price:
            level_type = "hỗ trợ"
            icon = "🔻"
        else:
            level_type = "trùng giá"
            icon = "📍"
        
        levels.append({
            "name": name,
            "value": round(value, 2),
            "type": level_type,
            "diff_pct": round(diff_pct, 2),
            "icon": icon,
            "desc": desc,
        })
    
    # Sort by value desc
    levels.sort(key=lambda x: x["value"], reverse=True)
    return levels


async def _fetch_fireant_history(client, symbol, start_date, end_date):
    token = _get_fireant_token()
    if not token: return None
    url = f"{_FIREANT_BASE}/symbols/{symbol}/historical-quotes?startDate={start_date}&endDate={end_date}&offset=0&limit=300"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    try:
        r = await client.get(url, headers=headers, timeout=10.0)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list): return data
        return None
    except Exception as e:
        logger.debug(f"[ichimoku] fail {symbol}: {e}")
        return None


async def get_ichimoku(symbol):
    symbol = symbol.upper().strip()
    now = _time.time()
    cached = _CACHE.get(symbol)
    if cached and (now - cached["at"]) < _CACHE_TTL:
        return {**cached["data"], "cached": True}
    
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
    
    async with httpx.AsyncClient() as client:
        hist = await _fetch_fireant_history(client, symbol, start, end)
    
    if not hist or len(hist) < 80:
        return {"error": f"Không đủ data cho {symbol}"}
    
    try:
        sorted_hist = sorted(hist, key=lambda x: x.get("date", ""))
    except Exception:
        sorted_hist = hist
    
    highs, lows, closes, dates = [], [], [], []
    for row in sorted_hist:
        h = _safe_float(row.get("priceHigh"))
        l = _safe_float(row.get("priceLow"))
        c = _safe_float(row.get("priceClose"))
        d = row.get("date", "")
        if h is None or l is None or c is None: continue
        highs.append(h); lows.append(l); closes.append(c); dates.append(d)
    
    if len(closes) < 80:
        return {"error": f"Data không đủ sạch cho {symbol}"}
    
    result = compute_ichimoku(highs, lows, closes)
    if "error" in result:
        return result
    
    output = {
        "symbol": symbol,
        "data_points": len(closes),
        "latest_date": dates[-1] if dates else None,
        "current": result["current"],
        "signal": result["signal"],
        "analysis": result["analysis"],
        "strategy": result["strategy"],
        "key_levels": result["key_levels"],
        "updated_at": datetime.now().isoformat(),
    }
    
    _CACHE[symbol] = {"at": now, "data": output}
    return output


# Scanner (same as before)
DEFAULT_ICHIMOKU_UNIVERSE = [
    "VCB", "BID", "CTG", "TCB", "MBB", "VPB", "ACB", "HDB", "STB", "SHB",
    "VIC", "VHM", "VRE", "NVL", "KDH", "DXG", "PDR", "NLG",
    "HPG", "HSG", "NKG",
    "VNM", "MSN", "SAB", "MWG", "PNJ", "FPT", "CMG",
    "GAS", "PLX", "BSR", "PVD", "PVS",
    "SSI", "VCI", "VND", "HCM",
    "POW", "REE", "GMD", "VJC",
    "DGC", "DCM", "DPM", "DHG",
    "DBC", "VHC", "ANV", "FRT", "DGW",
]


def get_ichimoku_universe():
    symbols = set(DEFAULT_ICHIMOKU_UNIVERSE)
    try:
        from app.db.database import get_db
        with get_db() as conn:
            cursor = conn.execute("SELECT DISTINCT symbol FROM watchlist_items")
            for row in cursor.fetchall():
                sym = row["symbol"] if hasattr(row, "keys") else row[0]
                if sym: symbols.add(sym.upper())
    except Exception: pass
    symbols.discard("VNINDEX")
    return sorted(symbols)


_SCAN_CACHE: Dict[str, Any] = {"data": None, "at": 0}
_SCAN_CACHE_TTL = 900


async def scan_ichimoku(filter_signal=None, force_refresh=False):
    now = _time.time()
    if not force_refresh and _SCAN_CACHE["data"] and (now - _SCAN_CACHE["at"]) < _SCAN_CACHE_TTL:
        cached = dict(_SCAN_CACHE["data"])
        cached["cached"] = True
        if filter_signal:
            cached["matches"] = [m for m in cached["matches"] if m["signal"]["level"] == filter_signal]
        return cached
    
    universe = get_ichimoku_universe()
    if not universe: return {"error": "Universe rỗng", "matches": []}
    
    logger.info(f"[ichimoku] Scanning {len(universe)}...")
    start_time = _time.time()
    
    results = []
    BATCH_SIZE = 10
    BATCH_DELAY = 0.5
    
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
    
    async with httpx.AsyncClient() as client:
        for i in range(0, len(universe), BATCH_SIZE):
            batch = universe[i:i + BATCH_SIZE]
            try:
                batch_hist = await asyncio.gather(
                    *[_fetch_fireant_history(client, sym, start, end) for sym in batch],
                    return_exceptions=True,
                )
                for sym, hist in zip(batch, batch_hist):
                    if isinstance(hist, Exception) or not hist or len(hist) < 80: continue
                    try:
                        sorted_hist = sorted(hist, key=lambda x: x.get("date", ""))
                        highs, lows, closes = [], [], []
                        for row in sorted_hist:
                            h = _safe_float(row.get("priceHigh"))
                            l = _safe_float(row.get("priceLow"))
                            c = _safe_float(row.get("priceClose"))
                            if h is None or l is None or c is None: continue
                            highs.append(h); lows.append(l); closes.append(c)
                        if len(closes) < 80: continue
                        result = compute_ichimoku(highs, lows, closes)
                        if "error" in result: continue
                        results.append({
                            "symbol": sym,
                            "price": result["current"]["price"],
                            "signal": result["signal"],
                            "current": result["current"],
                        })
                    except Exception as e:
                        logger.debug(f"[ichimoku] {sym}: {e}")
            except Exception as e:
                logger.warning(f"[ichimoku] Batch {i} fail: {e}")
            if i + BATCH_SIZE < len(universe):
                await asyncio.sleep(BATCH_DELAY)
    
    elapsed = _time.time() - start_time
    results.sort(key=lambda x: x["signal"]["score"], reverse=True)
    
    counts = {"strong_buy": 0, "buy": 0, "neutral": 0, "sell": 0, "strong_sell": 0}
    for r in results:
        lvl = r["signal"]["level"]
        if lvl in counts: counts[lvl] += 1
    
    output = {
        "matches": results,
        "summary": {"total": len(results), **counts},
        "scan_duration_s": round(elapsed, 1),
        "updated_at": datetime.now().isoformat(),
    }
    _SCAN_CACHE["data"] = output
    _SCAN_CACHE["at"] = now
    
    if filter_signal:
        output = dict(output)
        output["matches"] = [m for m in output["matches"] if m["signal"]["level"] == filter_signal]
    
    return output
