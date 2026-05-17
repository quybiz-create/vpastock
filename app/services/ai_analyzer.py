"""AI analyzer dung Claude Haiku 4.5."""
from __future__ import annotations
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
from loguru import logger

from app.config import settings


_ai_cache: dict = {}


SYSTEM_PROMPT = """Ban la chuyen gia phan tich ky thuat chung khoan Viet Nam voi 20 nam kinh nghiem, thanh thao:
- VPA (Volume Price Action) theo phong cach Anna Coulling, Tom Williams
- Phuong phap Wyckoff (Accumulation, Markup, Distribution, Markdown)
- Phan tich dong tien va hanh vi smart money

Ban LUON tra loi bang tieng Viet chuyen nganh. Ban KHONG dua ra loi khuyen dau tu ca nhan
ma chi phan tich dien bien ky thuat mot cach khach quan. NDT phai tu chiu trach nhiem.

QUAN TRONG: Output PHAI la JSON hop le theo schema. Khong giai thich truoc/sau JSON.
Khong dung markdown code fence."""


ANALYSIS_PROMPT_TEMPLATE = """Phan tich ky thuat ma {symbol}:

## Du lieu gia (10 phien gan nhat)
{recent_candles}

## Indicators
- Gia: {price}
- MA20: {ma20} (gia {ma20_state})
- MA50: {ma50} (gia {ma50_state})
- RSI(14): {rsi}
- ADX(14): {adx}  +DI: {plus_di}  -DI: {minus_di}
- Volume ratio: {vol_ratio}x MA20
- VPA: {vpa}
- VPA 5 phien: {recent_vpa}

Tra ve JSON:
{{
  "verdict": "BUY" | "HOLD" | "SELL",
  "confidence": <0-100>,
  "wyckoff_phase": "<phase>",
  "vpa_summary": "<tieng Viet, duoi 200 tu>",
  "money_flow_summary": "<tieng Viet, duoi 100 tu>",
  "key_points": ["<diem 1>", "<diem 2>", "<diem 3>"],
  "risk_warning": "<canh bao rui ro>",
  "entry_zone": <gia hoac null>,
  "stop_loss": <gia hoac null>,
  "target_1": <gia hoac null>,
  "target_2": <gia hoac null>
}}

Chi tra ve JSON."""


class AIAnalyzer:
    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not settings.ANTHROPIC_API_KEY:
                raise ValueError("ANTHROPIC_API_KEY chua cau hinh")
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        return self._client

    @staticmethod
    def _make_cache_key(symbol: str, df: pd.DataFrame) -> str:
        last = df.iloc[-1]
        key_str = f"{symbol}_{last.name.date()}_{last['close']:.2f}_{last['volume']:.0f}"
        return hashlib.md5(key_str.encode()).hexdigest()

    @staticmethod
    def _format_candles(df: pd.DataFrame, n: int = 10) -> str:
        recent = df.tail(n)
        lines = []
        for idx, row in recent.iterrows():
            change = (row["close"] - row["open"]) / row["open"] * 100
            lines.append(
                f"  {idx.strftime('%Y-%m-%d')}: "
                f"O={row['open']:.2f} H={row['high']:.2f} L={row['low']:.2f} "
                f"C={row['close']:.2f} ({change:+.2f}%) Vol={row['volume']:,.0f}"
            )
        return "\n".join(lines)

    @staticmethod
    def _build_prompt(symbol: str, df: pd.DataFrame) -> str:
        last = df.iloc[-1]
        recent_vpa = df["vpa"].iloc[-5:].tolist()

        def _fmt(v, dec=2):
            return f"{v:.{dec}f}" if pd.notna(v) else "N/A"

        return ANALYSIS_PROMPT_TEMPLATE.format(
            symbol=symbol,
            recent_candles=AIAnalyzer._format_candles(df, 10),
            price=_fmt(last["close"]),
            ma20=_fmt(last.get("ma20")),
            ma20_state="tren" if last["close"] > last.get("ma20", last["close"]) else "duoi",
            ma50=_fmt(last.get("ma50")),
            ma50_state="tren" if last["close"] > last.get("ma50", last["close"]) else "duoi",
            rsi=_fmt(last.get("rsi"), 1),
            adx=_fmt(last.get("adx"), 1),
            plus_di=_fmt(last.get("plus_di"), 1),
            minus_di=_fmt(last.get("minus_di"), 1),
            vol_ratio=_fmt(last.get("vol_ratio")),
            vpa=last["vpa"],
            recent_vpa=" -> ".join(recent_vpa),
        )

    async def analyze(self, symbol: str, df_with_indicators: pd.DataFrame) -> dict:
        cache_key = self._make_cache_key(symbol, df_with_indicators)
        if cache_key in _ai_cache:
            cached_time, cached_result = _ai_cache[cache_key]
            if datetime.now() - cached_time < timedelta(minutes=settings.AI_CACHE_MINUTES):
                return cached_result

        client = self._get_client()
        prompt = self._build_prompt(symbol, df_with_indicators)

        try:
            response = await client.messages.create(
                model=settings.AI_MODEL,
                max_tokens=settings.AI_MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            result = json.loads(content)
            result["_meta"] = {
                "symbol": symbol,
                "generated_at": datetime.now().isoformat(),
                "model": settings.AI_MODEL,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
            _ai_cache[cache_key] = (datetime.now(), result)
            return result

        except Exception as e:
            logger.error(f"AI analyze loi cho {symbol}: {e}")
            return self._fallback(symbol, str(e))

    @staticmethod
    def _fallback(symbol: str, error: str) -> dict:
        return {
            "verdict": "HOLD",
            "confidence": 0,
            "wyckoff_phase": "Khong xac dinh",
            "vpa_summary": f"Khong the phan tich AI. Loi: {error}",
            "money_flow_summary": "N/A",
            "key_points": ["AI tam thoi khong kha dung"],
            "risk_warning": "AI gap loi, vui long tham khao chi bao khac.",
            "entry_zone": None,
            "stop_loss": None,
            "target_1": None,
            "target_2": None,
            "_meta": {"symbol": symbol, "error": error},
        }


ai_analyzer = AIAnalyzer()