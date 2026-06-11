"""
Phase 16A: CANSLIM Scanner (v3 - Adapted for VN market)

7 tiêu chí CANSLIM (adapted from William O'Neil):
- C: ROE ≥ 15% (proxy cho EPS growth - chất lượng lợi nhuận VCSH)
- A: ROIC ≥ 15% (proxy cho annual earnings - hiệu quả vốn đầu tư)
- N: Giá ≥ 90% đỉnh 52 tuần (new highs)
- S: Vol > 1.5× MA20 (supply/demand)
- L: YTD vượt VNI YTD + 10% (leader)
- I: Nợ/VCSH < 1 (institutional quality - tài chính lành mạnh)
- M: VNI > MA50 (market direction)

Sources:
- FireAnt /symbols/{ticker}/historical-quotes: OHLCV
- FireAnt /symbols/{ticker}/financial-indicators: ROE, ROIC, Nợ/VCSH

Bypass vnstock rate limit (sys.exit kill backend).
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

_CACHE: Dict[str, Any] = {"data": None, "at": 0}
_CACHE_TTL = 1800

_MARKET_CACHE: Dict[str, Any] = {"data": None, "at": 0}
_MARKET_CACHE_TTL = 600


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


DEFAULT_CANSLIM_UNIVERSE = [
    "VCB", "BID", "CTG", "TCB", "MBB", "VPB", "ACB", "HDB", "STB", "SHB",
    "TPB", "VIB",
    "VIC", "VHM", "VRE", "NVL", "KDH", "DXG", "PDR", "NLG",
    "HPG", "HSG", "NKG",
    "VNM", "MSN", "SAB", "MWG", "PNJ", "FPT", "CMG",
    "GAS", "PLX", "BSR", "PVD", "PVS",
    "SSI", "VCI", "VND", "HCM",
    "POW", "REE", "GMD", "VJC",
    "DGC", "DCM", "DPM", "DHG",
    "DBC", "VHC", "ANV", "FRT", "DGW",
]


def get_universe() -> List[str]:
    symbols = set(DEFAULT_CANSLIM_UNIVERSE)
    try:
        from app.db.database import get_db
        with get_db() as conn:
            cursor = conn.execute("SELECT DISTINCT symbol FROM watchlist_items")
            for row in cursor.fetchall():
                sym = row["symbol"] if hasattr(row, "keys") else row[0]
                if sym:
                    symbols.add(sym.upper())
    except Exception as e:
        logger.debug(f"[canslim] watchlist load skip: {e}")
    symbols.discard("VNINDEX")
    return sorted(symbols)


# ============================================================
# FIREANT HELPERS
# ============================================================

async def _fa_get(client: httpx.AsyncClient, path: str, timeout: float = 8.0) -> Optional[Any]:
    token = _get_fireant_token()
    if not token:
        return None
    url = f"{_FIREANT_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        r = await client.get(url, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 401:
            logger.error("[canslim] FireAnt 401 - token expired")
        return None
    except Exception as e:
        logger.debug(f"[canslim] FA fail {path}: {e}")
        return None


async def _fetch_fireant_history(
    client: httpx.AsyncClient, symbol: str, start_date: str, end_date: str,
) -> Optional[List[Dict[str, Any]]]:
    path = f"/symbols/{symbol}/historical-quotes?startDate={start_date}&endDate={end_date}&offset=0&limit=300"
    data = await _fa_get(client, path, timeout=10.0)
    if isinstance(data, list):
        return data
    return None


async def _fetch_fireant_ratios(client: httpx.AsyncClient, symbol: str) -> Optional[Dict[str, float]]:
    """Fetch financial ratios từ FireAnt.
    
    Format response (list các indicators):
    [
      {'shortName': 'ROE', 'name': 'ROE (%)', 'value': 24.82, ...},
      {'shortName': 'ROIC', 'value': 23.37, ...},
      {'shortName': 'Nợ/VCSH', 'value': 0.71, ...},
      ...
    ]
    
    Returns dict: {'ROE': 24.82, 'ROIC': 23.37, 'NoVCSH': 0.71, ...}
    """
    path = f"/symbols/{symbol}/financial-indicators"
    data = await _fa_get(client, path, timeout=8.0)
    if not isinstance(data, list):
        return None
    
    ratios = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        short = (item.get("shortName") or "").strip()
        name = (item.get("name") or "").strip()
        value = _safe_float(item.get("value"))
        if value is None:
            continue
        
        # Mapping - dùng cả shortName và name để chắc chắn match
        short_lower = short.lower()
        name_lower = name.lower()
        
        if "roe" in short_lower or "roe" in name_lower:
            ratios["ROE"] = value
        elif "roa" in short_lower or "roa" in name_lower:
            ratios["ROA"] = value
        elif "roic" in short_lower or "roic" in name_lower:
            ratios["ROIC"] = value
        elif "roce" in short_lower or "roce" in name_lower:
            ratios["ROCE"] = value
        elif "nợ/vcsh" in short_lower or "no/vcsh" in short_lower or "debt" in name_lower.lower():
            ratios["NoVCSH"] = value
        elif "p/e" in short_lower or short_lower == "pe":
            ratios["PE"] = value
        elif "p/b" in short_lower or short_lower == "pb":
            ratios["PB"] = value
        elif "biên ln gộp" in name_lower or "gross margin" in name_lower:
            ratios["GrossMargin"] = value
        elif "biên ln ròng" in name_lower or "net margin" in name_lower:
            ratios["NetMargin"] = value
    
    return ratios if ratios else None


# ============================================================
# MARKET CONTEXT
# ============================================================

async def get_market_context() -> Dict[str, Any]:
    now = _time.time()
    if _MARKET_CACHE["data"] and (now - _MARKET_CACHE["at"]) < _MARKET_CACHE_TTL:
        return _MARKET_CACHE["data"]
    
    try:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=300)).strftime("%Y-%m-%d")
        ytd_start = datetime(datetime.now().year, 1, 1).strftime("%Y-%m-%d")
        
        async with httpx.AsyncClient() as client:
            hist = await _fetch_fireant_history(client, "VNINDEX", start, end)
        
        if not hist or len(hist) < 50:
            return {"trend_ok": False, "vni_ytd_pct": 0, "vni_close": None}
        
        try:
            sorted_h = sorted(hist, key=lambda x: x.get("date", ""))
        except Exception:
            sorted_h = hist
        
        closes = []
        for row in sorted_h:
            c = _safe_float(row.get("priceClose"))
            if c is not None and c > 0:
                closes.append((row.get("date", ""), c))
        
        if len(closes) < 50:
            return {"trend_ok": False, "vni_ytd_pct": 0, "vni_close": None}
        
        close_values = [c[1] for c in closes]
        close_now = close_values[-1]
        ma50 = sum(close_values[-50:]) / 50
        ma200 = sum(close_values[-200:]) / 200 if len(close_values) >= 200 else None
        
        ytd_closes = [c[1] for c in closes if c[0] >= ytd_start]
        if len(ytd_closes) >= 2:
            ytd_pct = ((close_now - ytd_closes[0]) / ytd_closes[0]) * 100 if ytd_closes[0] > 0 else 0
        else:
            ytd_pct = 0
        
        trend_ok = close_now > ma50
        
        result = {
            "trend_ok": trend_ok,
            "vni_close": round(close_now, 2),
            "vni_ma50": round(ma50, 2),
            "vni_ma200": round(ma200, 2) if ma200 else None,
            "vni_ytd_pct": round(ytd_pct, 2),
            "above_ma50": trend_ok,
            "above_ma200": bool(ma200 and close_now > ma200),
        }
        
        _MARKET_CACHE["data"] = result
        _MARKET_CACHE["at"] = now
        return result
    
    except Exception as e:
        logger.warning(f"[canslim] market_context fail: {e}")
        return {"trend_ok": False, "vni_ytd_pct": 0, "vni_close": None}


# ============================================================
# COMPUTE CRITERIA FOR ONE SYMBOL
# ============================================================

async def _compute_one_symbol(
    symbol: str, market_ctx: Dict[str, Any], fa_client: httpx.AsyncClient,
) -> Optional[Dict[str, Any]]:
    try:
        end = datetime.now().strftime("%Y-%m-%d")
        start_1y = (datetime.now() - timedelta(days=370)).strftime("%Y-%m-%d")
        ytd_start = datetime(datetime.now().year, 1, 1).strftime("%Y-%m-%d")
        
        hist_task = _fetch_fireant_history(fa_client, symbol, start_1y, end)
        ratios_task = _fetch_fireant_ratios(fa_client, symbol)
        
        hist, ratios = await asyncio.gather(hist_task, ratios_task, return_exceptions=True)
        
        if isinstance(hist, Exception) or not hist or len(hist) < 60:
            return None
        if isinstance(ratios, Exception):
            ratios = None
        ratios = ratios or {}
        
        try:
            sorted_hist = sorted(hist, key=lambda x: x.get("date", ""))
        except Exception:
            sorted_hist = hist
        
        rows = []
        for row in sorted_hist:
            c = _safe_float(row.get("priceClose"))
            h = _safe_float(row.get("priceHigh"))
            v = _safe_float(row.get("totalVolume") or row.get("volume"))
            d = row.get("date", "")
            if c is not None and c > 0:
                rows.append({"date": d, "close": c, "high": h or c, "volume": v or 0})
        
        if len(rows) < 60:
            return None
        
        close_now = rows[-1]["close"]
        
        vols = [r["volume"] for r in rows]
        vol_now = vols[-1]
        vol_ma20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else vol_now
        vol_ratio = vol_now / vol_ma20 if vol_ma20 > 0 else 1.0
        
        highs = [r["high"] for r in rows[-252:]]
        high_52w = max(highs) if highs else close_now
        pct_from_high = (close_now / high_52w * 100) if high_52w > 0 else 0
        
        ytd_rows = [r for r in rows if r["date"] >= ytd_start]
        if len(ytd_rows) >= 2:
            close_start_ytd = ytd_rows[0]["close"]
            ytd_pct = ((close_now - close_start_ytd) / close_start_ytd) * 100 if close_start_ytd > 0 else 0
        else:
            ytd_pct = 0
        
        vni_ytd = market_ctx.get("vni_ytd_pct", 0)
        rs_excess = ytd_pct - vni_ytd
        
        # ===== 7 Criteria (ADAPTED) =====
        criteria = {}
        
        # C: ROE >= 15% (proxy cho EPS growth - chất lượng lợi nhuận VCSH)
        roe = ratios.get("ROE")
        c_pass = roe is not None and roe >= 15
        c_detail = f"ROE = {roe:.1f}%" if roe is not None else "N/A"
        criteria["C"] = {
            "name": "Current ROE",
            "name_vi": "ROE",
            "pass": c_pass,
            "detail": c_detail,
            "threshold": "ROE ≥ 15%",
        }
        
        # A: ROIC >= 15% (proxy cho annual growth - hiệu quả vốn đầu tư)
        roic = ratios.get("ROIC")
        a_pass = roic is not None and roic >= 15
        a_detail = f"ROIC = {roic:.1f}%" if roic is not None else "N/A"
        criteria["A"] = {
            "name": "Annual ROIC",
            "name_vi": "ROIC",
            "pass": a_pass,
            "detail": a_detail,
            "threshold": "ROIC ≥ 15%",
        }
        
        # N: New highs
        n_pass = pct_from_high >= 90
        criteria["N"] = {
            "name": "New Highs",
            "name_vi": "Gần đỉnh 52w",
            "pass": n_pass,
            "detail": f"{pct_from_high:.1f}% so với đỉnh 52w ({high_52w:.0f})",
            "threshold": "≥ 90% đỉnh 52w",
        }
        
        # S: Supply/Demand
        s_pass = vol_ratio >= 1.5
        criteria["S"] = {
            "name": "Supply/Demand",
            "name_vi": "Cung cầu",
            "pass": s_pass,
            "detail": f"Vol = {vol_ratio:.2f}× MA20",
            "threshold": "Vol ≥ 1.5× MA20",
        }
        
        # L: Leader
        l_pass = rs_excess >= 10
        criteria["L"] = {
            "name": "Leader",
            "name_vi": "Dẫn dắt",
            "pass": l_pass,
            "detail": f"YTD {ytd_pct:+.1f}% vs VNI {vni_ytd:+.1f}% (chênh {rs_excess:+.1f}%)",
            "threshold": "YTD > VNI + 10%",
        }
        
        # I: Nợ/VCSH < 1 (proxy cho institutional quality - tài chính lành mạnh)
        debt_eq = ratios.get("NoVCSH")
        i_pass = debt_eq is not None and debt_eq < 1
        i_detail = f"Nợ/VCSH = {debt_eq:.2f}" if debt_eq is not None else "N/A"
        criteria["I"] = {
            "name": "Institutional Quality",
            "name_vi": "Tài chính",
            "pass": i_pass,
            "detail": i_detail,
            "threshold": "Nợ/VCSH < 1",
        }
        
        # M: Market direction
        m_pass = bool(market_ctx.get("trend_ok"))
        criteria["M"] = {
            "name": "Market",
            "name_vi": "Thị trường",
            "pass": m_pass,
            "detail": f"VNI {market_ctx.get('vni_close','?')} {'>' if m_pass else '<'} MA50 {market_ctx.get('vni_ma50','?')}",
            "threshold": "VNI > MA50",
        }
        
        total_score = sum(1 for c in criteria.values() if c["pass"])
        
        if total_score >= 6:
            tag, tag_class = "🌟 Strong CANSLIM", "strong"
        elif total_score >= 4:
            tag, tag_class = "💪 CANSLIM Setup", "setup"
        else:
            tag, tag_class = "⚪ Yếu", "weak"
        
        return {
            "symbol": symbol,
            "score": total_score,
            "max_score": 7,
            "tag": tag,
            "tag_class": tag_class,
            "price": round(close_now, 2),
            "vol_ratio": round(vol_ratio, 2),
            "pct_from_52w_high": round(pct_from_high, 2),
            "ytd_pct": round(ytd_pct, 2),
            "rs_excess": round(rs_excess, 2),
            "roe": round(roe, 2) if roe is not None else None,
            "roic": round(roic, 2) if roic is not None else None,
            "debt_equity": round(debt_eq, 2) if debt_eq is not None else None,
            "criteria": criteria,
        }
    
    except Exception as e:
        logger.debug(f"[canslim] {symbol} fail: {e}")
        return None


# ============================================================
# MAIN SCAN
# ============================================================

async def scan_canslim(force_refresh: bool = False) -> Dict[str, Any]:
    now = _time.time()
    if not force_refresh and _CACHE["data"] and (now - _CACHE["at"]) < _CACHE_TTL:
        cached = dict(_CACHE["data"])
        cached["cached"] = True
        return cached
    
    token = _get_fireant_token()
    if not token:
        return {"error": "FIREANT_TOKEN không có trong .env", "matches": [], "summary": {}}
    
    universe = get_universe()
    if not universe:
        return {"error": "Universe rỗng", "matches": []}
    
    market_ctx = await get_market_context()
    
    logger.info(f"[canslim] Scanning {len(universe)} via FireAnt...")
    start_time = _time.time()
    
    results: List[Dict[str, Any]] = []
    
    BATCH_SIZE = 10
    BATCH_DELAY = 0.5
    
    async with httpx.AsyncClient() as fa_client:
        for i in range(0, len(universe), BATCH_SIZE):
            batch = universe[i:i + BATCH_SIZE]
            try:
                batch_results = await asyncio.gather(
                    *[_compute_one_symbol(sym, market_ctx, fa_client) for sym in batch],
                    return_exceptions=True,
                )
                for r in batch_results:
                    if isinstance(r, dict):
                        results.append(r)
            except Exception as e:
                logger.warning(f"[canslim] Batch {i} fail: {e}")
            if i + BATCH_SIZE < len(universe):
                await asyncio.sleep(BATCH_DELAY)
    
    elapsed = _time.time() - start_time
    logger.info(f"[canslim] Scanned {len(results)}/{len(universe)} in {elapsed:.1f}s")
    
    results.sort(key=lambda x: (x["score"], x["rs_excess"]), reverse=True)
    
    strong = sum(1 for r in results if r["score"] >= 6)
    setup = sum(1 for r in results if 4 <= r["score"] < 6)
    weak = sum(1 for r in results if r["score"] < 4)
    
    result = {
        "matches": results,
        "summary": {
            "total": len(results),
            "strong": strong,
            "setup": setup,
            "weak": weak,
            "market": market_ctx,
        },
        "scan_duration_s": round(elapsed, 1),
        "data_source": "FireAnt",
        "updated_at": datetime.now().isoformat(),
    }
    
    _CACHE["data"] = result
    _CACHE["at"] = now
    
    return result


if __name__ == "__main__":
    async def _test():
        result = await scan_canslim()
        print(f"Summary: {result.get('summary', {})}")
        for r in result.get("matches", [])[:5]:
            print(f"{r['tag']} {r['symbol']} - {r['score']}/7 (ROE={r.get('roe')}, ROIC={r.get('roic')})")
    
    asyncio.run(_test())
