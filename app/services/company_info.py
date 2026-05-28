"""
Company Info module - Phase 6
Fetch comprehensive company data from vnstock VCI:
- Overview (name, sector, profile, rating, target...)
- Stats (market cap, shares, foreign ownership)
- Trading (avg vol/val, high/low 1Y)
- Financial 8 quarters (revenue, profit, EPS, margins)
"""
from __future__ import annotations
import math
import asyncio
from typing import Dict, Any, List, Optional
from loguru import logger


def _safe_float(v: Any) -> Optional[float]:
    """Convert to float, return None if NaN/None/invalid."""
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> Optional[int]:
    """Convert to int, return None if invalid."""
    f = _safe_float(v)
    return int(f) if f is not None else None


def _safe_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if s.lower() in ('nan', 'none', ''):
        return None
    return s


def _get_quarter_values(df, item_name: str, quarter_cols: List[str]) -> List[Optional[float]]:
    """Extract values for specific item across quarters."""
    if df is None or df.empty:
        return [None] * len(quarter_cols)
    
    row = df[df['item'] == item_name]
    if row.empty:
        return [None] * len(quarter_cols)
    
    row = row.iloc[0]
    return [_safe_float(row.get(q)) for q in quarter_cols]


def fetch_company_sync(symbol: str) -> Dict[str, Any]:
    """
    Sync function to fetch all company data from vnstock.
    Returns structured dict ready for JSON response.
    """
    from vnstock import Vnstock
    
    symbol = symbol.upper().strip()
    result: Dict[str, Any] = {
        "symbol": symbol,
        "overview": None,
        "stats": None,
        "trading": None,
        "financial": None,
        "errors": [],
    }
    
    # === 1. Overview from company.overview() ===
    try:
        v = Vnstock().stock(symbol=symbol, source='VCI')
        ov_df = v.company.overview()
        if ov_df is not None and not ov_df.empty:
            o = ov_df.iloc[0].to_dict()
            
            result["overview"] = {
                "symbol": _safe_str(o.get("symbol")) or symbol,
                "name": _safe_str(o.get("organ_name")),
                "short_name": _safe_str(o.get("organ_short_name")),
                "sector": _safe_str(o.get("sector")),
                "exchange": _safe_str(o.get("com_group_code")),
                "listing_date": _safe_str(o.get("listing_date")),
                "profile": _safe_str(o.get("company_profile")),
                "rating": _safe_str(o.get("rating")),
                "rating_as_of": _safe_str(o.get("rating_as_of")),
                "target_price": _safe_float(o.get("target_price")),
                "current_price": _safe_float(o.get("current_price")),
                "upside_to_target_pct": _safe_float(o.get("upside_to_target_percent")),
                "projected_tsr_pct": _safe_float(o.get("projected_tsr_percentage")),
                "analyst": _safe_str(o.get("analyst")),
                "is_bank": bool(o.get("is_bank", False)),
                "icb_lv2": _safe_str(o.get("icb_code_lv2")),
                "icb_lv4": _safe_str(o.get("icb_code_lv4")),
            }
            
            result["stats"] = {
                "market_cap": _safe_float(o.get("market_cap")),
                "issue_share": _safe_int(o.get("issue_share")),
                "free_float": _safe_int(o.get("free_float")),
                "free_float_pct": _safe_float(o.get("free_float_percentage")),
                "foreigner_pct": _safe_float(o.get("foreigner_percentage")),
                "max_foreign_pct": _safe_float(o.get("maximum_foreign_percentage")),
                "state_pct": _safe_float(o.get("state_percentage")),
                "dividend_per_share": _safe_float(o.get("dividend_per_share_tsr")),
            }
            
            result["trading"] = {
                "current_price": _safe_float(o.get("current_price")),
                "high_1y": _safe_float(o.get("highest_price1_year")),
                "low_1y": _safe_float(o.get("lowest_price1_year")),
                "avg_value_1m": _safe_float(o.get("average_match_value1_month")),
                "avg_volume_1m": _safe_float(o.get("average_match_volume1_month")),
            }
    except Exception as e:
        msg = f"overview fetch fail: {e}"
        logger.warning(f"[COMPANY {symbol}] {msg}")
        result["errors"].append(msg)
    
    # === 2. Financial - 8 quarters from income_statement ===
    try:
        if 'v' not in locals():
            v = Vnstock().stock(symbol=symbol, source='VCI')
        
        df = v.finance.income_statement(period='quarter', lang='vi')
        if df is not None and not df.empty:
            # Get quarter columns (skip item/item_en/item_id)
            all_cols = df.columns.tolist()
            quarter_cols = [c for c in all_cols if c not in ('item', 'item_en', 'item_id')]
            # Take latest 8 quarters (already in descending order)
            quarter_cols = quarter_cols[:8]
            
            result["financial"] = {
                "quarters": quarter_cols,  # ["2026-Q1", "2025-Q4", ...]
                "revenue": _get_quarter_values(df, 'Doanh thu thuần', quarter_cols),
                "gross_profit": _get_quarter_values(df, 'Lợi nhuận gộp', quarter_cols),
                "cogs": _get_quarter_values(df, 'Giá vốn hàng bán', quarter_cols),
                "operating_profit": _get_quarter_values(df, 'Lãi/(lỗ) từ hoạt động kinh doanh', quarter_cols),
                "pretax_profit": _get_quarter_values(df, 'Lãi/(lỗ) trước thuế', quarter_cols),
                "net_profit": _get_quarter_values(df, 'Lãi/(lỗ) thuần sau thuế', quarter_cols),
                "owner_profit": _get_quarter_values(df, 'Lợi nhuận của Cổ đông của Công ty mẹ', quarter_cols),
                "eps_basic": _get_quarter_values(df, 'Lãi cơ bản trên cổ phiếu (VND)', quarter_cols),
                "interest_expense": _get_quarter_values(df, 'Chi phí lãi vay', quarter_cols),
                "financial_income": _get_quarter_values(df, 'Doanh thu hoạt động tài chính', quarter_cols),
                "selling_expense": _get_quarter_values(df, 'Chi phí bán hàng', quarter_cols),
                "admin_expense": _get_quarter_values(df, 'Chi phí quản lý doanh nghiệp', quarter_cols),
            }
            
            # Compute margins (%) — gross margin, net margin
            margins = {"gross_margin": [], "net_margin": []}
            for i, _ in enumerate(quarter_cols):
                rev = result["financial"]["revenue"][i]
                gp = result["financial"]["gross_profit"][i]
                np_v = result["financial"]["net_profit"][i]
                margins["gross_margin"].append(
                    round(gp / rev * 100, 2) if (rev and gp and rev != 0) else None
                )
                margins["net_margin"].append(
                    round(np_v / rev * 100, 2) if (rev and np_v and rev != 0) else None
                )
            result["financial"].update(margins)
    except Exception as e:
        msg = f"financial fetch fail: {e}"
        logger.warning(f"[COMPANY {symbol}] {msg}")
        result["errors"].append(msg)
    
    return result


async def fetch_company(symbol: str) -> Dict[str, Any]:
    """Async wrapper - run sync fetch in thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_company_sync, symbol)


# Test standalone
if __name__ == "__main__":
    import json
    result = fetch_company_sync("HSG")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:3000])
