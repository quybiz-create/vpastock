"""
Daily Brief module - Phase 8B
Generate morning brief and send to Telegram.

Workflow:
1. Get tickers from watchlist "Demo" (DB)
2. For each ticker, fetch indicators + signals
3. Compose context for Claude AI
4. AI generates brief (Markdown, concise)
5. Send to Telegram via Bot API

Run via:
    python -m app.cli.send_brief
    # Or systemd timer at 8 AM
"""
from __future__ import annotations
import os
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from loguru import logger
import httpx

# Auto load .env (cho CLI standalone)
try:
    from dotenv import load_dotenv
    from pathlib import Path
    # Tìm .env ở root project
    _env_path = Path(__file__).parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
        logger.info(f"[BRIEF] Loaded .env from {_env_path}")
except ImportError:
    pass

# Telegram config from env
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_API = "https://api.telegram.org"

# Anthropic Claude config
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = "claude-sonnet-4-5"  # latest
CLAUDE_MAX_TOKENS = 2000


async def get_watchlist_demo_tickers() -> List[str]:
    """Get tickers from 'Demo' watchlist in DB."""
    try:
        from app.services.watchlist_store import list_watchlists, list_tickers
        # Demo watchlist là watchlist mặc định cho user mặc định
        wls = await list_watchlists(user_fp="default")
        demo = next((w for w in wls if w.get("name", "").lower() == "demo"), None)
        if not demo:
            # Fallback: lấy watchlist đầu tiên
            if wls:
                demo = wls[0]
            else:
                logger.warning("[BRIEF] No watchlist found")
                return []
        tickers = await list_tickers(demo["id"])
        return [t["symbol"] for t in tickers] if tickers else []
    except Exception as e:
        logger.warning(f"[BRIEF] DB watchlist fail: {e}, fallback to hardcoded list")
        # Fallback hardcoded - các mã phổ biến
        return ["VNINDEX", "HSG", "FPT", "VIC", "MWG", "HPG"]


async def fetch_market_context() -> Dict[str, Any]:
    """Fetch overall market state: VNINDEX + Fear&Greed."""
    try:
        from app.services.market import compute_fear_greed
        from app.data.vnstock_client import vnstock_client
        from app.core.indicators import compute_all
        from datetime import timedelta
        
        # Fear & Greed
        fg = await compute_fear_greed()
        
        # VNINDEX detail
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        df = await vnstock_client.get_history("VNINDEX", start=start, end=end)
        
        vnindex_data = {}
        if df is not None and not df.empty:
            df = df[~df.index.duplicated(keep='last')].sort_index()
            df_full = compute_all(df)
            last = df_full.iloc[-1]
            prev = df_full.iloc[-2] if len(df_full) >= 2 else None
            close_now = float(last["close"])
            close_prev = float(prev["close"]) if prev is not None else close_now
            pct = ((close_now - close_prev) / close_prev) * 100 if close_prev > 0 else 0
            vnindex_data = {
                "close": round(close_now, 2),
                "change_pct": round(pct, 2),
                "rsi": round(float(last.get("rsi", 0)), 1) if last.get("rsi") else None,
                "ma20": round(float(last.get("ma20", 0)), 2) if last.get("ma20") else None,
                "ma50": round(float(last.get("ma50", 0)), 2) if last.get("ma50") else None,
            }
        
        return {
            "fear_greed": fg,
            "vnindex": vnindex_data,
        }
    except Exception as e:
        logger.warning(f"[BRIEF] Market context fail: {e}")
        return {}


async def fetch_ticker_brief(symbol: str) -> Dict[str, Any]:
    """Fetch concise data for one ticker."""
    try:
        from app.data.vnstock_client import vnstock_client
        from app.core.indicators import compute_all
        from datetime import timedelta
        
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        df = await vnstock_client.get_history(symbol, start=start, end=end)
        
        if df is None or df.empty:
            return {"symbol": symbol, "error": "No data"}
        
        df = df[~df.index.duplicated(keep='last')].sort_index()
        df_full = compute_all(df)
        last = df_full.iloc[-1]
        prev = df_full.iloc[-2] if len(df_full) >= 2 else None
        
        close_now = float(last["close"])
        close_prev = float(prev["close"]) if prev is not None else close_now
        pct = ((close_now - close_prev) / close_prev) * 100 if close_prev > 0 else 0
        
        return {
            "symbol": symbol,
            "price": round(close_now, 2),
            "change_pct": round(pct, 2),
            "volume": int(last.get("volume", 0)) if not pd_isna(last.get("volume")) else 0,
            "rsi": round(float(last.get("rsi")), 1) if not pd_isna(last.get("rsi")) else None,
            "ma20": round(float(last.get("ma20")), 2) if not pd_isna(last.get("ma20")) else None,
            "vol_ratio": round(float(last.get("vol_ratio")), 2) if not pd_isna(last.get("vol_ratio")) else None,
            "vpa": str(last.get("vpa", "Normal")),
        }
    except Exception as e:
        logger.warning(f"[BRIEF] Ticker {symbol} fail: {e}")
        return {"symbol": symbol, "error": str(e)}


def pd_isna(v) -> bool:
    """Safe NaN check."""
    import math
    if v is None:
        return True
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False


def build_context_for_ai(market: Dict, tickers_data: List[Dict]) -> str:
    """Compose human-readable context for Claude."""
    parts = []
    
    # Market overview
    fg = market.get("fear_greed", {})
    vni = market.get("vnindex", {})
    parts.append("=== TỔNG QUAN THỊ TRƯỜNG ===")
    if vni:
        sign = "+" if vni.get("change_pct", 0) >= 0 else ""
        parts.append(f"VNINDEX: {vni.get('close', '--')} ({sign}{vni.get('change_pct', 0)}%) | RSI: {vni.get('rsi', '--')} | MA20: {vni.get('ma20', '--')} | MA50: {vni.get('ma50', '--')}")
    if fg.get("score") is not None:
        parts.append(f"Fear & Greed: {fg.get('score')} - {fg.get('label')} {fg.get('emoji', '')}")
    
    # Tickers
    parts.append("\n=== MÃ TRONG WATCHLIST ===")
    for t in tickers_data:
        if t.get("error"):
            parts.append(f"{t['symbol']}: lỗi - {t['error']}")
            continue
        sign = "+" if t.get("change_pct", 0) >= 0 else ""
        parts.append(
            f"{t['symbol']}: {t.get('price', '--')} ({sign}{t.get('change_pct', 0)}%) | "
            f"RSI: {t.get('rsi', '--')} | "
            f"Vol/MA20: {t.get('vol_ratio', '--')}x | "
            f"VPA: {t.get('vpa', '--')}"
        )
    
    return "\n".join(parts)


async def generate_brief_with_ai(context: str) -> str:
    """Send context to Claude, get back Markdown brief."""
    if not ANTHROPIC_API_KEY:
        logger.warning("[BRIEF] No Anthropic API key")
        return "⚠️ Chưa cấu hình Anthropic API key"
    
    prompt = f"""Bạn là chuyên gia phân tích chứng khoán Việt Nam.

DỮ LIỆU SÁNG NAY ({datetime.now().strftime('%d/%m/%Y')}):

{context}

Viết Daily Brief NGẮN GỌN (dưới 300 từ) bằng tiếng Việt cho nhà đầu tư cá nhân, định dạng Markdown sạch dành cho Telegram. Cấu trúc:

📊 **Tổng quan thị trường**: 1-2 câu về VNINDEX và Fear & Greed.

🎯 **Watchlist đáng chú ý**: chỉ liệt kê 2-3 mã quan trọng nhất (có biến động lớn, RSI extreme, hoặc volume đột biến). Mỗi mã 1 dòng: hành động ngắn + lý do.

⚠️ **Cảnh báo**: rủi ro/cơ hội đặc biệt (nếu có).

LƯU Ý:
- KHÔNG copy lại số liệu thô, chỉ ra ý nghĩa và hành động.
- Tránh thuật ngữ phức tạp.
- Cuối brief: 1 câu kết khuyến nghị chiến lược chung.
- KHÔNG dùng disclaimer dài.
"""
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": CLAUDE_MAX_TOKENS,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            data = r.json()
            content = data.get("content", [])
            if content and content[0].get("type") == "text":
                return content[0]["text"]
            return "(AI không trả về nội dung)"
    except Exception as e:
        logger.exception(f"[BRIEF] AI call fail: {e}")
        return f"⚠️ Lỗi gọi AI: {e}"


async def send_telegram(message: str) -> bool:
    """Send message via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("[BRIEF] Telegram not configured")
        return False
    
    url = f"{TELEGRAM_API}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            })
            r.raise_for_status()
            logger.info(f"[BRIEF] Telegram sent OK")
            return True
    except Exception as e:
        logger.exception(f"[BRIEF] Telegram send fail: {e}")
        # Retry without Markdown (in case formatting break)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(url, json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": message,
                    "disable_web_page_preview": True,
                })
                r.raise_for_status()
                logger.info(f"[BRIEF] Telegram sent OK (plain text fallback)")
                return True
        except Exception as e2:
            logger.exception(f"[BRIEF] Telegram fallback fail: {e2}")
            return False


async def run_daily_brief() -> Dict[str, Any]:
    """Main entry: generate brief + send to Telegram."""
    logger.info("[BRIEF] === Starting Daily Brief ===")
    
    # 1. Get tickers
    tickers = await get_watchlist_demo_tickers()
    if not tickers:
        msg = "⚠️ Watchlist trống, không có mã để phân tích."
        await send_telegram(msg)
        return {"ok": False, "reason": "empty_watchlist"}
    
    logger.info(f"[BRIEF] Tickers: {tickers}")
    
    # 2. Fetch market context
    market = await fetch_market_context()
    
    # 3. Fetch each ticker
    tickers_data = []
    for sym in tickers[:8]:  # Limit 8 tickers
        data = await fetch_ticker_brief(sym)
        tickers_data.append(data)
        await asyncio.sleep(0.4)  # avoid rate limit
    
    # 4. Build context + ask AI
    context = build_context_for_ai(market, tickers_data)
    logger.info(f"[BRIEF] Context length: {len(context)} chars")
    
    brief = await generate_brief_with_ai(context)
    
    # 5. Add header
    today = datetime.now().strftime("%d/%m/%Y")
    full_message = f"🌅 *VPASTOCK Daily Brief - {today}*\n\n{brief}\n\n_Tự động · không phải lời khuyên đầu tư_"
    
    # 6. Send Telegram
    ok = await send_telegram(full_message)
    
    logger.info(f"[BRIEF] === Done. Sent: {ok} ===")
    return {"ok": ok, "tickers_count": len(tickers_data), "brief_length": len(brief)}


# Standalone CLI
if __name__ == "__main__":
    result = asyncio.run(run_daily_brief())
    print(f"\nResult: {result}")
