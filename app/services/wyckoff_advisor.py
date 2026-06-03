"""
Wyckoff AI Advisor - Phase 9C

Gom data từ nhiều nguồn:
- Wyckoff analysis (setup, phase, events, trading range)
- FireAnt news + sentiment (tin gần đây)
- F&G Index (tâm lý thị trường chung)
- Current price + key indicators

Gọi Claude AI với prompt chi tiết để sinh ra "Trading Advisor" report:
- Diễn giải từng event Wyckoff
- Đánh giá tác động news + sentiment
- Kết luận tổng thể + chiến lược cụ thể (entry/SL/TP)

Cache 30 phút per symbol (đắt, ít thay đổi trong ngắn hạn).
"""
from __future__ import annotations
import os
import time
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from loguru import logger
import httpx


_AI_CACHE: Dict[str, Dict[str, Any]] = {}
_AI_CACHE_TTL = 30 * 60   # 30 phút


def _format_wyckoff_for_prompt(wy: Dict[str, Any]) -> str:
    """Format Wyckoff result thành text dễ đọc cho prompt."""
    lines = []
    setup = wy.get("setup", "none")
    phase = wy.get("phase", "none")
    conf = wy.get("confidence", 0)
    
    setup_vi = {
        "accumulation": "🟢 TÍCH LŨY (Accumulation)",
        "distribution": "🔴 PHÂN PHỐI (Distribution)",
        "none": "⚪ KHÔNG XÁC ĐỊNH",
    }.get(setup, setup)
    
    lines.append(f"Setup: {setup_vi}")
    lines.append(f"Phase hiện tại: {phase}")
    lines.append(f"Độ tin cậy: {int(conf * 100)}%")
    lines.append(f"Xu hướng trước TR: {wy.get('pre_trend', 'unknown')}")
    
    tr = wy.get("trading_range")
    if tr:
        lines.append(f"\nTrading Range (TR):")
        lines.append(f"  - Cao (kháng cự): {tr['high']}")
        lines.append(f"  - Giữa: {tr['mid']}")
        lines.append(f"  - Thấp (hỗ trợ): {tr['low']}")
        lines.append(f"  - Biên độ: {tr['range_pct']}%")
        lines.append(f"  - Kéo dài: {tr['bars_count']} phiên")
    
    events = wy.get("events", [])
    if events:
        lines.append(f"\n{len(events)} Events đã phát hiện:")
        for e in events:
            lines.append(f"  • {e['type']:12s} @ giá {e['price']}: {e['desc']}")
    
    lines.append(f"\nĐề xuất từ thuật toán: {wy.get('suggestion', '')}")
    return "\n".join(lines)


def _format_news_for_prompt(news: Dict[str, Any]) -> str:
    """Format news + sentiment thành text."""
    items = news.get("items", [])
    summary = news.get("summary", {})
    
    if not items:
        return "Không có tin tức gần đây."
    
    lines = [
        f"Tổng quan: {summary.get('overall', 'neutral')} "
        f"(+{summary.get('positive', 0)} tích cực / -{summary.get('negative', 0)} tiêu cực / "
        f"={summary.get('neutral', 0)} trung tính, điểm trung bình {summary.get('avg_score', 0)})",
        f"\nTop 5 tin gần nhất:",
    ]
    for i, it in enumerate(items[:5], 1):
        s = it.get("sentiment", {})
        emoji = s.get("emoji", "📰")
        date = (it.get("date") or "")[:10]
        title = it.get("title", "")[:120]
        lines.append(f"  {i}. {emoji} [{date}] {title}")
    return "\n".join(lines)


def _format_fg_for_prompt(fg: Dict[str, Any]) -> str:
    """Format F&G Index thành text."""
    score = fg.get("score", 50)
    label = fg.get("label", "N/A")
    emoji = fg.get("emoji", "")
    
    vnindex = fg.get("vnindex") or {}
    pct_ma = vnindex.get("pct_above_ma")
    
    lines = [
        f"Chỉ số F&G: {score}/100 ({emoji} {label})",
        f"VN-Index: {vnindex.get('value', 'N/A')} (cách MA200: {pct_ma}%)" if pct_ma is not None else "",
    ]
    
    comps = fg.get("components") or {}
    if comps:
        lines.append(f"\nCác thành phần:")
        for key, label_vn in [("rsi", "RSI"), ("ma200", "MA200"), ("volume", "Volume"), ("volatility", "Biến động"), ("momentum", "Momentum")]:
            c = comps.get(key, {})
            if c:
                lines.append(f"  - {label_vn} = {c.get('value', 'N/A')} (điểm {c.get('score', 0)})")
    
    return "\n".join(filter(None, lines))


def _build_advisor_prompt(
    symbol: str,
    wyckoff_data: Dict[str, Any],
    news_data: Optional[Dict[str, Any]],
    fg_data: Optional[Dict[str, Any]],
    current_price: Optional[float],
) -> str:
    """Build prompt cho Claude AI Advisor."""
    wy_text = _format_wyckoff_for_prompt(wyckoff_data)
    news_text = _format_news_for_prompt(news_data) if news_data else "Không có dữ liệu tin tức."
    fg_text = _format_fg_for_prompt(fg_data) if fg_data else "Không có dữ liệu F&G Index."
    
    price_line = f"Giá hiện tại: {current_price}" if current_price else ""
    
    return f"""Bạn là chuyên viên phân tích chứng khoán theo phương pháp Wyckoff với 20 năm kinh nghiệm trên thị trường Việt Nam.

Hãy phân tích SIÊU CHI TIẾT mã **{symbol}** dựa trên 3 nguồn dữ liệu dưới đây.

═══════════════════════════════════════════════
📊 1. PHÂN TÍCH WYCKOFF (THUẬT TOÁN)
═══════════════════════════════════════════════
{wy_text}
{price_line}

═══════════════════════════════════════════════
📰 2. TIN TỨC + SENTIMENT
═══════════════════════════════════════════════
{news_text}

═══════════════════════════════════════════════
😱 3. TÂM LÝ THỊ TRƯỜNG (FEAR & GREED)
═══════════════════════════════════════════════
{fg_text}

═══════════════════════════════════════════════
✍️ YÊU CẦU PHÂN TÍCH:
═══════════════════════════════════════════════

Hãy viết phân tích theo cấu trúc CHÍNH XÁC sau (dùng đúng các tag markdown):

## 🎯 TÍN HIỆU TỔNG QUAN
1-2 câu súc tích: hiện tại CỰC KỲ QUAN TRỌNG / QUAN TRỌNG / BÌNH THƯỜNG / không có tín hiệu. Setup là gì? Phase nào?

## 📍 DIỄN BIẾN HIỆN TẠI (3-5 ý)
Giải thích các events Wyckoff đã phát hiện THEO THỨ TỰ THỜI GIAN. Mỗi event là 1 dòng:
- "Tại giá XYZ, [tên event] xuất hiện → ý nghĩa là gì"
- Liên hệ với position của giá hiện tại so với TR.

## 🔮 KỊCH BẢN CÓ THỂ XẢY RA
Đưa ra 2-3 kịch bản:
- ✅ **Kịch bản tích cực**: nếu giá làm X → khả năng Y → đích Z
- ⚠️ **Kịch bản tiêu cực**: nếu giá làm X → khả năng Y → đích Z
- 🟡 **Kịch bản trung tính** (nếu có)

## 📰 TÁC ĐỘNG TIN TỨC
Nhận xét ngắn về news + sentiment có cộng hưởng/đối lập với phân tích kỹ thuật không.

## 😱 BỐI CẢNH THỊ TRƯỜNG
F&G Index đang ở mức nào? Có nên thận trọng hơn / quyết đoán hơn không?

## 💼 CHIẾN LƯỢC GIAO DỊCH CỤ THỂ
Đưa ra checklist hành động RÕ RÀNG, ngắn gọn. Mỗi dòng bắt đầu bằng emoji + hành động:
- ⚠️/🛑/✅/👀/📉/📈
- Cụ thể giá entry / stop loss / target profit (CON SỐ thực, không nói chung chung)
- Nếu KHÔNG nên giao dịch → nói rõ tại sao

## ⚖️ MỨC ĐỘ TIN CẬY
Đánh giá 1-2 câu về độ tin cậy của tín hiệu này (cao/trung bình/thấp) và nên đặt vị thế bao nhiêu % vốn (theo Wyckoff thông thường 2-5% cho 1 mã).

LƯU Ý:
- KHÔNG khuyến nghị mua bán cuồng nhiệt, luôn cảnh báo rủi ro
- Dùng các con số CỤ THỂ từ data (giá TR, giá hiện tại, events)
- Tiếng Việt rõ ràng, ngắn gọn, dễ hiểu cho nhà đầu tư cá nhân
- KHÔNG dùng từ "chắc chắn", "100%", "không thể sai"
- Phân tích trung lập, không thiên về một phía
"""


async def get_ai_advisor(
    symbol: str,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Lấy phân tích AI tổng hợp cho symbol.
    
    Gom data Wyckoff + News + F&G + price, gọi Claude AI.
    Cache 30 phút per symbol.
    """
    symbol = symbol.upper().strip()
    now = time.time()
    
    # Cache check
    if not force_refresh:
        cached = _AI_CACHE.get(symbol)
        if cached and (now - cached["at"]) < _AI_CACHE_TTL:
            result = dict(cached["data"])
            result["cached"] = True
            return result
    
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "symbol": symbol,
            "advisor": "❌ Tính năng AI cần API key. Vui lòng cấu hình ANTHROPIC_API_KEY trong .env",
            "error": "no_api_key",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    
    # Gom data từ các service (best-effort)
    wyckoff_data = None
    news_data = None
    fg_data = None
    current_price = None
    
    try:
        # 1. Wyckoff
        from app.services.wyckoff import analyze_wyckoff
        from app.data.vnstock_client import vnstock_client
        from datetime import timedelta
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
        df = await vnstock_client.get_history(symbol, start=start, end=end)
        if df is not None and not df.empty:
            df = df[~df.index.duplicated(keep="last")].sort_index()
            bars = []
            for idx, row in df.iterrows():
                try:
                    t = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
                except Exception:
                    t = str(idx)
                bars.append({
                    "time": t,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0) or 0),
                })
            wyckoff_data = analyze_wyckoff(bars, period=200)
            if bars:
                current_price = bars[-1]["close"]
    except Exception as e:
        logger.warning(f"[advisor] wyckoff load fail: {e}")
    
    try:
        # 2. News (chỉ lấy nếu service có)
        from app.services.news_sentiment import get_news
        news_data = await get_news(symbol)
    except Exception as e:
        logger.warning(f"[advisor] news load fail: {e}")
    
    try:
        # 3. F&G Index (tâm lý thị trường chung, không phụ thuộc symbol)
        from app.services.market import compute_fear_greed
        fg_data = await compute_fear_greed()
    except Exception as e:
        logger.warning(f"[advisor] fg load fail: {e}")
    
    if not wyckoff_data or wyckoff_data.get("setup") == "none":
        return {
            "symbol": symbol,
            "advisor": "⚠️ Chưa hình thành setup Wyckoff rõ ràng cho mã này. Hãy chờ thị trường tích lũy/phân phối trước khi giao dịch theo Wyckoff.",
            "wyckoff_setup": wyckoff_data.get("setup") if wyckoff_data else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    
    # Build prompt
    prompt = _build_advisor_prompt(symbol, wyckoff_data, news_data, fg_data, current_price)
    
    # Gọi Claude AI
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 2500,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            data = r.json()
            text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text += block.get("text", "")
            text = text.strip()
            
            # Detect overall verdict từ keywords
            text_lower = text.lower()
            if "kịch bản tích cực" in text_lower and (
                "kịch bản tiêu cực" in text_lower or "rủi ro" in text_lower
            ):
                # Phân tích có cả hai mặt
                if wyckoff_data.get("setup") == "accumulation" and wyckoff_data.get("phase") in ("D", "E"):
                    verdict = "bullish"
                elif wyckoff_data.get("setup") == "distribution" and wyckoff_data.get("phase") in ("D", "E"):
                    verdict = "bearish"
                else:
                    verdict = "neutral"
            else:
                verdict = "neutral"
            
            result = {
                "symbol": symbol,
                "advisor": text,
                "verdict": verdict,
                "wyckoff_setup": wyckoff_data.get("setup"),
                "wyckoff_phase": wyckoff_data.get("phase"),
                "wyckoff_confidence": wyckoff_data.get("confidence"),
                "current_price": current_price,
                "data_used": {
                    "wyckoff": bool(wyckoff_data),
                    "news": bool(news_data and news_data.get("items")),
                    "fg_index": bool(fg_data and not fg_data.get("error")),
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            _AI_CACHE[symbol] = {"at": now, "data": result}
            return result
    except httpx.TimeoutException:
        return {
            "symbol": symbol,
            "advisor": "⏰ AI phân tích bị timeout. Vui lòng thử lại sau.",
            "error": "timeout",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.exception(f"[advisor] {symbol} AI fail: {e}")
        return {
            "symbol": symbol,
            "advisor": f"⚠️ Lỗi khi gọi AI: {str(e)[:120]}",
            "error": str(e)[:200],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
