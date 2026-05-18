"""
Quan ly danh sach ma CP Viet Nam.
- Cache ket qua tu vnstock Listing API
- Fallback ve list hardcode khi API loi
- Async wrapper de khong block FastAPI
"""
from __future__ import annotations
from typing import List, Optional
from datetime import datetime, timedelta
import asyncio
from loguru import logger


VN30 = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
]

HOSE_FALLBACK = VN30 + [
    "ANV", "APH", "BCG", "BFC", "BMP", "BSI", "BVB", "CII", "CMG", "CMX",
    "CRE", "CSV", "CTD", "CTR", "DBC", "DCM", "DGC", "DGW", "DIG", "DPM",
    "DRC", "DXG", "DXS", "EIB", "FCN", "FRT", "FTS", "GEX", "GMD", "HAH",
    "HAX", "HBC", "HCM", "HDC", "HDG", "HHV", "HMC", "HNG", "HSG", "HT1",
    "IDI", "IJC", "IMP", "ITA", "KBC", "KDC", "KDH", "KOS", "LCG", "LHG",
    "LPB", "MSB", "NKG", "NLG", "NT2", "OCB", "ORS", "PAN", "PC1", "PDR",
    "PET", "PGV", "PHR", "PNJ", "POM", "PPC", "PVD", "PVT", "QCG", "REE",
    "SAM", "SBT", "SCS", "SHI", "SJS", "TCH", "TLG", "TNG", "TPC", "VCG",
    "VCI", "VDS", "VGC", "VIX", "VND", "VPI", "VSC",
]

HNX_FALLBACK = [
    "CEO", "DXP", "IDC", "L14", "LAS", "MBS", "PVI", "PVS", "SHS", "TIG",
    "TVC", "VC2", "VCS", "VFS", "VIG",
]


_symbol_cache: dict = {}
_cache_ttl_hours = 24


async def get_all_symbols(exchange: str = "ALL") -> List[str]:
    """
    Lay danh sach ma CP theo san.
    exchange: HOSE, HNX, UPCOM, ALL
    """
    exchange = exchange.upper()
    cache_key = f"symbols_{exchange}"

    if cache_key in _symbol_cache:
        cached_at, cached_data = _symbol_cache[cache_key]
        if datetime.now() - cached_at < timedelta(hours=_cache_ttl_hours):
            return cached_data

    try:
        loop = asyncio.get_event_loop()
        symbols = await loop.run_in_executor(None, _fetch_listing_sync, exchange)
        if symbols and len(symbols) > 0:
            _symbol_cache[cache_key] = (datetime.now(), symbols)
            logger.info(f"Lay duoc {len(symbols)} ma tu vnstock cho {exchange}")
            return symbols
    except Exception as e:
        logger.warning(f"vnstock Listing loi: {e}")

    logger.info(f"Dung fallback list cho {exchange}")
    if exchange == "HOSE":
        return HOSE_FALLBACK
    elif exchange == "HNX":
        return HNX_FALLBACK
    elif exchange == "ALL":
        return list(dict.fromkeys(HOSE_FALLBACK + HNX_FALLBACK))
    return HOSE_FALLBACK


def _fetch_listing_sync(exchange: str) -> List[str]:
    """Goi vnstock Listing API sync (trong thread pool)."""
    from vnstock import Listing
    listing = Listing()
    df = listing.symbols_by_exchange()

    if df is None or len(df) == 0:
        return []

    if exchange in ("HOSE", "HNX", "UPCOM"):
        df = df[df["exchange"] == exchange]

    if "type" in df.columns:
        df = df[df["type"] == "STOCK"]

    symbols = df["symbol"].dropna().tolist()
    symbols = [s.upper().strip() for s in symbols if s and len(s) <= 5]
    return sorted(set(symbols))