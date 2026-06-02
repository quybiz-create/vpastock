"""
Phase 8C: FireAnt news + sentiment analysis.

- fetch_news(symbol): lấy N tin mới nhất từ FireAnt API
- keyword_sentiment(text): phân loại tích cực/tiêu cực/trung tính theo từ khóa
- analyze_news_deep(symbol): gom tất cả tin → Claude AI tổng hợp 1 đoạn

Cache:
- News list: 15 phút / symbol (FireAnt update không thường xuyên)
- AI deep: 1 giờ / symbol (đắt hơn, ít thay đổi)

ENV:
- FIREANT_TOKEN: JWT bearer token (đã có trong .env)
- ANTHROPIC_API_KEY: cho AI deep analysis
"""
from __future__ import annotations
import asyncio
import html as _html
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from loguru import logger
import httpx


# ============================================================
# Config
# ============================================================
_FIREANT_BASE = "https://restv2.fireant.vn"
_NEWS_LIMIT = 10
_NEWS_CACHE_TTL = 15 * 60   # 15 phút
_AI_CACHE_TTL = 60 * 60      # 1 giờ

_news_cache: Dict[str, Dict[str, Any]] = {}
_ai_cache: Dict[str, Dict[str, Any]] = {}


# ============================================================
# Keyword Sentiment (free, instant)
# ============================================================
# Từ khóa VN tài chính phân theo cảm xúc
POSITIVE_KEYWORDS = [
    # Tăng trưởng
    "tăng trưởng", "tăng mạnh", "bứt phá", "tăng vọt", "kỷ lục",
    "đạt đỉnh", "vượt kỳ vọng", "tích cực", "khởi sắc", "phục hồi",
    # Lãi/lợi nhuận
    "lãi", "lợi nhuận", "có lãi", "lãi ròng", "lãi đậm", "lãi gấp",
    "doanh thu tăng", "lợi nhuận tăng", "lpst tăng", "eps tăng",
    # Cổ tức / mua lại
    "chia cổ tức", "trả cổ tức", "cổ tức bằng tiền", "cổ tức bằng cổ phiếu",
    "mua lại cổ phiếu quỹ", "mua cổ phiếu quỹ", "phát hành thêm",
    # Hợp đồng / dự án
    "trúng thầu", "ký hợp đồng", "đầu tư mới", "dự án mới", "mở rộng",
    "khánh thành", "khởi công",
    # Đánh giá
    "khuyến nghị mua", "khuyến nghị MUA", "outperform", "overweight",
    "BUY", "tăng giá mục tiêu", "nâng giá mục tiêu",
    # Khác
    "đạt mục tiêu", "hoàn thành kế hoạch", "vượt kế hoạch",
]

NEGATIVE_KEYWORDS = [
    # Giảm
    "giảm sâu", "giảm mạnh", "lao dốc", "lùi sâu", "rớt giá", "sụt giảm",
    "thua lỗ", "bị bán tháo", "thoái vốn",
    # Lỗ
    "lỗ", "lỗ ròng", "lỗ nặng", "âm vốn", "phá sản", "mất khả năng",
    "doanh thu giảm", "lợi nhuận giảm", "lpst giảm", "eps giảm",
    # Xử phạt / điều tra
    "xử phạt", "vi phạm", "điều tra", "khởi tố", "truy tố", "bị bắt",
    "thanh tra", "cảnh báo", "đình chỉ", "huỷ niêm yết", "hủy niêm yết",
    "cổ phiếu kiểm soát", "cổ phiếu hạn chế",
    # Đánh giá
    "khuyến nghị bán", "underperform", "underweight", "SELL",
    "hạ giá mục tiêu", "giảm giá mục tiêu",
    # Khác
    "không đạt kế hoạch", "thấp hơn kỳ vọng", "rủi ro",
]


def keyword_sentiment(title: str, summary: str = "") -> Dict[str, Any]:
    """Phân tích sentiment dựa trên từ khóa. Trả về dict {label, score, keywords}.
    
    label: 'positive' / 'negative' / 'neutral'
    score: -1.0 (rất tiêu cực) → 1.0 (rất tích cực)
    """
    text = ((title or "") + " " + (summary or "")).lower()
    
    pos_hits = [kw for kw in POSITIVE_KEYWORDS if kw.lower() in text]
    neg_hits = [kw for kw in NEGATIVE_KEYWORDS if kw.lower() in text]
    
    pos_score = len(pos_hits)
    neg_score = len(neg_hits)
    diff = pos_score - neg_score
    
    if diff >= 2:
        label = "very_positive"
        score = min(1.0, diff / 4)
        emoji = "😊"
    elif diff == 1:
        label = "positive"
        score = 0.4
        emoji = "🙂"
    elif diff == 0:
        label = "neutral"
        score = 0.0
        emoji = "😐"
    elif diff == -1:
        label = "negative"
        score = -0.4
        emoji = "😟"
    else:
        label = "very_negative"
        score = max(-1.0, diff / 4)
        emoji = "😨"
    
    return {
        "label": label,
        "score": round(score, 2),
        "emoji": emoji,
        "keywords": {
            "positive": pos_hits[:5],
            "negative": neg_hits[:5],
        },
    }


# ============================================================
# FireAnt fetch
# ============================================================
def _get_fireant_token() -> Optional[str]:
    return os.environ.get("FIREANT_TOKEN") or None


def _strip_html(html: str) -> str:
    """Strip HTML tags + decode HTML entities + collapse whitespace."""
    if not html:
        return ""
    # Decode HTML entities (&#253; -> ý, &amp; -> &)
    text = _html.unescape(html)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _truncate(text: str, n: int = 200) -> str:
    text = text or ""
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0] + "…"


async def _fetch_fireant_posts(symbol: str, limit: int = _NEWS_LIMIT) -> List[Dict[str, Any]]:
    """Gọi FireAnt API lấy posts (news + analysis) cho symbol."""
    token = _get_fireant_token()
    if not token:
        logger.warning("[news] FIREANT_TOKEN not set; cannot fetch news")
        return []
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    # FireAnt endpoint: GET /symbols/{symbol}/posts?type=0&offset=0&limit=N
    # type=0: tin tổng hợp; type=2: phân tích; bỏ type → mix
    url = f"{_FIREANT_BASE}/symbols/{symbol.upper()}/posts?offset=0&limit={limit}"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 401:
                logger.error("[news] FireAnt 401 — token hết hạn hoặc sai")
                return []
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list):
                return []
            return data
    except httpx.TimeoutException:
        logger.warning(f"[news] timeout fetching {symbol}")
        return []
    except Exception as e:
        logger.exception(f"[news] fetch fail {symbol}: {e}")
        return []


def _normalize_post(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert raw FireAnt post → unified shape used by frontend."""
    try:
        # Decode HTML entities trong title (FireAnt trả &#253;, &amp;...)
        title = _html.unescape((p.get("title") or "")).strip()
        # FireAnt có thể trả 'content' hoặc 'message' hoặc 'description'
        body_raw = p.get("content") or p.get("message") or p.get("description") or ""
        summary = _strip_html(body_raw)
        if not title and summary:
            title = _truncate(summary, 120)
        if not title:
            return None
        
        # link gốc
        link = p.get("link") or p.get("originalURL") or p.get("url") or ""
        
        # thời gian: 'date' / 'postedDate' / 'createdDate' ISO 8601
        date_str = (
            p.get("date") or p.get("postedDate") or p.get("createdDate")
            or p.get("publishedAt") or ""
        )
        
        # Sentiment keyword
        sent = keyword_sentiment(title, summary)
        
        return {
            "id": p.get("postID") or p.get("id") or p.get("postId"),
            "title": title,
            "summary": _truncate(summary, 280),
            "link": link,
            "source": p.get("source") or p.get("sourceName") or "FireAnt",
            "date": date_str,
            "sentiment": sent,
        }
    except Exception as e:
        logger.debug(f"[news] normalize fail: {e}")
        return None


# ============================================================
# Public API
# ============================================================
async def get_news(symbol: str, limit: int = _NEWS_LIMIT) -> Dict[str, Any]:
    """Lấy news đã chuẩn hoá + sentiment. Cache 15 phút."""
    symbol = symbol.upper().strip()
    now = time.time()
    
    cached = _news_cache.get(symbol)
    if cached and (now - cached["at"]) < _NEWS_CACHE_TTL:
        result = dict(cached["data"])
        result["cached"] = True
        return result
    
    raw = await _fetch_fireant_posts(symbol, limit=limit)
    items: List[Dict[str, Any]] = []
    for p in raw[:limit]:
        n = _normalize_post(p)
        if n:
            items.append(n)
    
    # Aggregate sentiment stats
    pos = sum(1 for x in items if x["sentiment"]["score"] > 0.1)
    neg = sum(1 for x in items if x["sentiment"]["score"] < -0.1)
    neu = len(items) - pos - neg
    
    if items:
        avg_score = sum(x["sentiment"]["score"] for x in items) / len(items)
    else:
        avg_score = 0.0
    
    overall = "neutral"
    if avg_score > 0.15:
        overall = "positive"
    elif avg_score < -0.15:
        overall = "negative"
    
    result = {
        "symbol": symbol,
        "count": len(items),
        "items": items,
        "summary": {
            "positive": pos,
            "negative": neg,
            "neutral": neu,
            "avg_score": round(avg_score, 2),
            "overall": overall,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    
    if items:
        _news_cache[symbol] = {"at": now, "data": result}
    
    return result


async def analyze_news_deep(symbol: str) -> Dict[str, Any]:
    """AI Claude tổng hợp tin tức thành 1 đoạn đánh giá chung.
    Cache 1 giờ per symbol."""
    symbol = symbol.upper().strip()
    now = time.time()
    
    cached = _ai_cache.get(symbol)
    if cached and (now - cached["at"]) < _AI_CACHE_TTL:
        result = dict(cached["data"])
        result["cached"] = True
        return result
    
    # Lấy news trước
    news = await get_news(symbol)
    items = news.get("items", [])
    if not items:
        return {
            "symbol": symbol,
            "analysis": "Không có tin tức gần đây cho mã này.",
            "verdict": "neutral",
            "items_analyzed": 0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    
    # Build prompt cho Claude
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("[news] ANTHROPIC_API_KEY not set; return fallback")
        return {
            "symbol": symbol,
            "analysis": "Tính năng AI cần API key. Vui lòng cấu hình ANTHROPIC_API_KEY trong .env",
            "verdict": "neutral",
            "items_analyzed": len(items),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error": "no_api_key",
        }
    
    bullets = []
    for i, it in enumerate(items, 1):
        date = it.get("date", "")[:10]
        bullets.append(f"{i}. [{date}] {it['title']}\n   {it['summary'][:180]}")
    news_text = "\n\n".join(bullets)
    
    prompt = (
        f"Bạn là chuyên viên phân tích chứng khoán Việt Nam. Dưới đây là {len(items)} "
        f"tin tức gần nhất về mã **{symbol}**. Hãy phân tích ngắn gọn (3-4 câu) theo các ý:\n"
        f"1. Tóm tắt chủ đề chính trong các tin\n"
        f"2. Đánh giá tổng quan tin tức tác động đến giá (tích cực / tiêu cực / trung tính)\n"
        f"3. Cảnh báo rủi ro hoặc cơ hội đáng chú ý (nếu có)\n"
        f"4. Kết luận: TÍCH CỰC / TRUNG TÍNH / TIÊU CỰC\n\n"
        f"TIN TỨC:\n{news_text}\n\n"
        f"Lưu ý: chỉ phân tích tin trên, không tự suy diễn. Tránh khuyến nghị mua/bán cụ thể. "
        f"Trả lời bằng tiếng Việt, ngắn gọn."
    )
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",  # Haiku rẻ nhất cho task này
                    "max_tokens": 600,
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
            
            # Detect verdict từ text
            text_lower = text.lower()
            if "kết luận: tích cực" in text_lower or "kết luận:** tích cực" in text_lower:
                verdict = "positive"
            elif "kết luận: tiêu cực" in text_lower or "kết luận:** tiêu cực" in text_lower:
                verdict = "negative"
            else:
                verdict = "neutral"
            
            result = {
                "symbol": symbol,
                "analysis": text,
                "verdict": verdict,
                "items_analyzed": len(items),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            _ai_cache[symbol] = {"at": now, "data": result}
            return result
    except httpx.TimeoutException:
        logger.warning(f"[news AI] timeout for {symbol}")
        return {
            "symbol": symbol,
            "analysis": "AI phân tích bị timeout. Thử lại sau.",
            "verdict": "neutral",
            "items_analyzed": len(items),
            "error": "timeout",
        }
    except Exception as e:
        logger.exception(f"[news AI] {symbol} fail: {e}")
        return {
            "symbol": symbol,
            "analysis": f"Lỗi khi gọi AI: {str(e)[:120]}",
            "verdict": "neutral",
            "items_analyzed": len(items),
            "error": str(e)[:200],
        }


# Standalone test
if __name__ == "__main__":
    import json
    
    async def _test():
        print("=== keyword_sentiment test ===")
        for t in [
            "VCB lãi kỷ lục năm 2025",
            "HSG bị xử phạt vi phạm thuế",
            "Công ty mở rộng nhà máy",
        ]:
            print(t, "→", keyword_sentiment(t))
        
        print("\n=== fetch news VIC ===")
        n = await get_news("VIC", limit=5)
        print(json.dumps(n, ensure_ascii=False, indent=2))
    
    asyncio.run(_test())
