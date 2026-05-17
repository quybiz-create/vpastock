"""Wrapper async cho vnstock library - dung KBS source."""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional, Literal
import asyncio
import pandas as pd
from loguru import logger


SourceType = Literal["KBS", "VCI", "TCBS", "MSN"]


class VnstockClient:
    """Async wrapper cho vnstock. KBS la primary (hoat dong tot tu may ca nhan)."""

    def __init__(self, primary: SourceType = "KBS", fallback: SourceType = "VCI"):
        self.primary = primary
        self.fallback = fallback

    async def get_history(
        self,
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        interval: str = "1D",
    ) -> pd.DataFrame:
        symbol = symbol.upper().strip()
        if end is None:
            end = datetime.now().strftime("%Y-%m-%d")
        if start is None:
            start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        loop = asyncio.get_event_loop()

        # Try primary (KBS)
        try:
            df = await loop.run_in_executor(
                None, self._fetch_quote, symbol, start, end, interval, self.primary
            )
            if df is not None and len(df) > 0:
                return df
        except Exception as e:
            logger.warning(f"Primary {self.primary} loi cho {symbol}: {e}")

        # Fallback
        try:
            logger.info(f"Fallback sang {self.fallback} cho {symbol}")
            df = await loop.run_in_executor(
                None, self._fetch_quote, symbol, start, end, interval, self.fallback
            )
            return df
        except Exception as e:
            logger.error(f"Ca 2 source deu loi cho {symbol}: {e}")
            raise

    @staticmethod
    def _fetch_quote(symbol: str, start: str, end: str, interval: str, source: str) -> pd.DataFrame:
        """Goi vnstock Quote module truc tiep (bypass Vnstock().stock() bi 403)."""
        from vnstock import Quote
        q = Quote(symbol=symbol, source=source)
        df = q.history(start=start, end=end, interval=interval)

        if df is None or len(df) == 0:
            return pd.DataFrame()

        # Chuan hoa columns
        df.columns = [c.lower() for c in df.columns]

        # Dat time lam index
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"])
            df = df.set_index("time")

        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Source {source} thieu column {col}")

        return df[required].sort_index()

    async def get_company_overview(self, symbol: str) -> dict:
        """Tam thoi tra ve placeholder - vnstock 4.x Company endpoint con loi 403."""
        return {
            "symbol": symbol.upper(),
            "name": symbol.upper(),
            "exchange": "HOSE",
            "industry": "N/A",
            "note": "Company overview tam thoi chua kha dung"
        }

    async def get_financial_ratios(self, symbol: str) -> dict:
        """Tam thoi tra ve placeholder - TCBS finance.ratio() khong con hoat dong."""
        return {
            "symbol": symbol.upper(),
            "note": "Financial ratios se them o Phase 2"
        }


vnstock_client = VnstockClient()