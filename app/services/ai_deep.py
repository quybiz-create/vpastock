"""
AI Deep Analysis - Phase 4
Tong hop TAT CA 12 features (VPA, T+2, Score, RSI Combo, EMA, ST, Pivot...) 
thanh bao cao chuyen sau bang Claude AI.

Streaming response qua SSE.
"""
from __future__ import annotations
import os
import json
from typing import AsyncGenerator
from pathlib import Path

from anthropic import AsyncAnthropic
from loguru import logger
from dotenv import load_dotenv

# Load .env
ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# Configuration
CLAUDE_MODEL = "claude-haiku-4-5"  # Nhanh + ren + du smart cho TA
MAX_TOKENS = 2048

# Initialize client (lazy)
_client = None

def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in .env")
        _client = AsyncAnthropic(api_key=api_key)
    return _client


def build_system_prompt() -> str:
    """System prompt - role + format guidelines."""
    return """Ban la chuyen gia phan tich ky thuat thi truong chung khoan Viet Nam, 
chuyen ve Volume Price Analysis (VPA) theo phuong phap Wyckoff/Tom Williams.

Ban danh gia 1 ma CP dua tren tat ca chi bao da co. Format output:

📊 **TÓM TẮT** (1-2 câu)
Nhận định ngắn gọn về xu hướng + cơ hội.

📈 **TÍN HIỆU CHÍNH**
- Bullet point các signals tích cực (Pivot, Cross, RSI Combo, VPA...)

⚠️ **RỦI RO**
- Bullet point các điểm cần lưu ý (MA200, ADX, divergence...)

💡 **KHUYẾN NGHỊ**
- ENTRY: khoảng giá
- STOP LOSS: giá cụ thể
- TARGET: 1-2 mức target
- R:R ước tính
- Position size suggestion

🎯 **KẾT LUẬN**
1 câu chốt: nên MUA / GIỮ / BÁN / TRÁNH

Ngon ngu: Tieng Viet. 
Giong: chuyen nghiep, ngan gon, khong dai dong. 
Khong dung markdown header (#).
Dung emoji va bullet (-) cho de doc."""


def build_user_prompt(symbol: str, data: dict) -> str:
    """User prompt - data tu 12 features."""
    parts = [f"Phan tich ma {symbol.upper()} dua tren cac chi bao sau:\n"]
    
    # 1. Indicators
    last = data.get("indicators", {}).get("last", {})
    if last:
        def f2(key):
            v = last.get(key)
            return f"{v:.2f}" if v is not None else "--"
        def f1(key):
            v = last.get(key)
            return f"{v:.1f}" if v is not None else "--"
        
        parts.append("**INDICATORS (gan nhat):**")
        parts.append(f"- Gia: {f2('price')}")
        parts.append(f"- MA20: {f2('ma20')} | MA50: {f2('ma50')} | MA200: {f2('ma200')}")
        parts.append(f"- RSI: {f1('rsi')} | MFI: {f1('mfi')}")
        parts.append(f"- MACD: {f2('macd')} / Signal: {f2('macd_signal')}")
        parts.append(f"- ADX: {f1('adx')} (+DI: {f1('plus_di')}, -DI: {f1('minus_di')})")
        parts.append(f"- Bollinger: U {f2('bb_upper')} / M {f2('bb_middle')} / L {f2('bb_lower')}")
        parts.append(f"- Volume Ratio: {f2('vol_ratio')}x MA20")
        if last.get('vpa'): 
            parts.append(f"- VPA Signal: **{last['vpa']}**")
        parts.append("")
    
    # 2. RSI Combo signals
    rsi_combo = data.get("rsi_combo", {})
    if rsi_combo and rsi_combo.get("counts"):
        c = rsi_combo["counts"]
        parts.append("**RSI COMBO SIGNALS (90 ngay gan nhat):**")
        parts.append(f"- Combo Buy: {c.get('combo_buy',0)} signals (chat luong cao)")
        parts.append(f"- Combo Exit: {c.get('combo_exit',0)} signals (canh bao chot loi)")
        parts.append(f"- Bull Divergence: {c.get('bull_div',0)} | Bear Divergence: {c.get('bear_div',0)}")
        parts.append(f"- RSI Buy: {c.get('rsi_buy',0)} | RSI Exit: {c.get('rsi_exit',0)}")
        parts.append("")
    
    # 3. EMA + SuperTrend
    ema_st = data.get("ema_supertrend", {})
    if ema_st:
        ema_c = ema_st.get("ema", {}).get("counts", {})
        st_c = ema_st.get("supertrend", {}).get("counts", {})
        parts.append("**EMA 20/40 + SUPERTREND:**")
        parts.append(f"- Golden Cross: {ema_c.get('golden_cross',0)} | Death Cross: {ema_c.get('death_cross',0)}")
        parts.append(f"- SuperTrend Buy: {st_c.get('buy',0)} | Sell: {st_c.get('sell',0)}")
        parts.append("")
    
    # 4. Pivot Finder (most important)
    pivot = data.get("pivots", {})
    if pivot:
        last_sig = pivot.get("last_signal")
        c = pivot.get("counts", {})
        parts.append("**PIVOT FINDER (chat luong cao - chuan AmiBroker):**")
        parts.append(f"- Tong Pivot Buy: {c.get('buy',0)} | Pivot Sell: {c.get('sell',0)}")
        if last_sig:
            parts.append(f"- TIN HIEU GAN NHAT: **{last_sig['type']}** @ {last_sig['price']:.2f} ({last_sig['bars_ago']} bars ago)")
        parts.append("")
    
    # 5. Risk metrics (neu co)
    if data.get("risk"):
        r = data["risk"]
        parts.append("**RISK METRICS:**")
        parts.append(f"- Setup Score: {r.get('setup_score', 'N/A')}/100")
        parts.append("")
    
    parts.append("\nHay phan tich tong hop va dua ra khuyen nghi cu the.")
    return "\n".join(parts)


async def analyze_stream(symbol: str, data: dict) -> AsyncGenerator[str, None]:
    """
    Stream phan tich AI tu Claude.
    Yields text chunks de SSE.
    """
    client = get_client()
    
    system = build_system_prompt()
    user = build_user_prompt(symbol, data)
    
    logger.info(f"[AI DEEP] Streaming for {symbol}, prompt {len(user)} chars")
    
    try:
        async with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            async for text in stream.text_stream:
                yield text
        
        # Get final message for usage
        final = await stream.get_final_message()
        logger.info(
            f"[AI DEEP] {symbol} done. "
            f"Input: {final.usage.input_tokens} tokens, "
            f"Output: {final.usage.output_tokens} tokens"
        )
    except Exception as e:
        logger.error(f"[AI DEEP] Error for {symbol}: {e}")
        yield f"\n\n⚠️ Loi phan tich AI: {str(e)}"


# Test standalone
if __name__ == "__main__":
    import asyncio
    
    sample_data = {
        "indicators": {
            "last": {
                "price": 18.0,
                "ma20": 18.5,
                "ma50": 19.2,
                "ma200": 22.0,
                "rsi": 45.5,
                "macd": -0.2,
                "macd_signal": 0.1,
                "adx": 21,
                "plus_di": 18,
                "minus_di": 23,
                "vol_ratio": 1.2,
                "vpa": "Spring",
            }
        },
        "rsi_combo": {"counts": {"combo_buy": 1, "combo_exit": 2, "bull_div": 2, "bear_div": 11, "rsi_buy": 2, "rsi_exit": 1}},
        "ema_supertrend": {
            "ema": {"counts": {"golden_cross": 3, "death_cross": 2}},
            "supertrend": {"counts": {"buy": 13, "sell": 13}},
        },
        "pivots": {
            "last_signal": {"type": "BUY", "price": 18.6, "bars_ago": 3},
            "counts": {"buy": 5, "sell": 4},
        },
    }
    
    async def test():
        print(f"\n=== AI Analysis for HSG ===\n")
        async for chunk in analyze_stream("HSG", sample_data):
            print(chunk, end="", flush=True)
        print("\n\n=== Done ===")
    
    asyncio.run(test())