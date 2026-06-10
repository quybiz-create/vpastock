"""
Phase 15A API: Candlestick & Price Action Pattern Detection

Endpoints:
- GET /api/patterns/detect/{symbol}?days=30
  → Detect patterns trên N ngày gần nhất

- GET /api/patterns/scan
  → Scan watchlist + universe tìm mã có pattern đẹp gần đây (1-3 ngày)
"""
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from datetime import datetime, timedelta
from loguru import logger

router = APIRouter()


@router.get("/detect/{symbol}")
async def detect_patterns(
    symbol: str,
    days: int = Query(30, ge=5, le=180, description="Số ngày lookback"),
):
    """Detect candlestick + price action patterns cho 1 mã.
    
    Returns: { symbol, patterns: [...], summary: {...} }
    """
    try:
        from app.data.vnstock_client import vnstock_client
        from app.core.pattern_detector import detect_all_patterns, get_pattern_summary
        
        symbol = symbol.upper().strip()
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days + 30)).strftime("%Y-%m-%d")
        
        df = await vnstock_client.get_history(symbol, start=start, end=end)
        if df is None or df.empty:
            raise HTTPException(404, f"Không có data cho {symbol}")
        
        df = df[~df.index.duplicated(keep='last')].sort_index()
        
        patterns = detect_all_patterns(df, lookback_days=days)
        summary = get_pattern_summary(patterns)
        
        return {
            "symbol": symbol,
            "lookback_days": days,
            "data_points": len(df),
            "patterns": patterns,
            "summary": summary,
            "updated_at": datetime.now().isoformat(),
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[patterns] detect fail {symbol}: {e}")
        raise HTTPException(500, str(e))


@router.get("/scan")
async def scan_patterns(
    days_recent: int = Query(3, ge=1, le=10, description="Chỉ lấy patterns trong N ngày gần nhất"),
    min_reliability: int = Query(60, ge=0, le=100, description="Lọc theo reliability tối thiểu"),
    direction: Optional[str] = Query(None, pattern="^(bullish|bearish|neutral)$"),
):
    """Scan toàn bộ universe + watchlist, tìm mã có pattern đẹp trong N ngày gần đây.
    
    Returns: { matches: [{symbol, patterns: [...]}], total }
    """
    try:
        from app.data.vnstock_client import vnstock_client
        from app.core.pattern_detector import detect_all_patterns
        import asyncio
        
        # Universe: dùng từ market_breadth_fireant nếu có
        try:
            from app.services.market_breadth_fireant import get_universe_symbols
            universe = get_universe_symbols()
        except ImportError:
            # Fallback: top liquid mã
            universe = [
                "VCB", "BID", "CTG", "TCB", "MBB", "VPB", "ACB",
                "VIC", "VHM", "VRE", "HPG", "HSG", "MWG", "FPT",
                "VNM", "MSN", "GAS", "PLX", "SSI", "VND",
            ]
        
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        
        today = datetime.now()
        cutoff = today - timedelta(days=days_recent)
        
        matches = []
        
        # Process in batches để tránh rate limit
        BATCH_SIZE = 5
        for i in range(0, len(universe), BATCH_SIZE):
            batch = universe[i:i + BATCH_SIZE]
            
            try:
                histories = await asyncio.gather(
                    *[vnstock_client.get_history(sym, start=start, end=end) for sym in batch],
                    return_exceptions=True,
                )
                
                for sym, hist in zip(batch, histories):
                    if isinstance(hist, Exception) or hist is None or hist.empty:
                        continue
                    try:
                        df = hist[~hist.index.duplicated(keep='last')].sort_index()
                        all_patterns = detect_all_patterns(df, lookback_days=10)
                        
                        # Filter: chỉ patterns trong N ngày gần nhất + reliability
                        recent_patterns = []
                        for p in all_patterns:
                            try:
                                p_date = datetime.strptime(p["date"], "%Y-%m-%d")
                                if p_date < cutoff:
                                    continue
                                if p["reliability"] < min_reliability:
                                    continue
                                if direction and p["direction"] != direction:
                                    continue
                                recent_patterns.append(p)
                            except Exception:
                                continue
                        
                        if recent_patterns:
                            matches.append({
                                "symbol": sym,
                                "patterns": recent_patterns[:3],   # top 3
                                "best_reliability": max(p["reliability"] for p in recent_patterns),
                            })
                    except Exception as e:
                        logger.debug(f"[patterns scan] {sym}: {e}")
                        continue
            
            except Exception as e:
                logger.warning(f"[patterns scan] batch fail: {e}")
            
            await asyncio.sleep(0.5)
        
        # Sort by best_reliability
        matches.sort(key=lambda x: x["best_reliability"], reverse=True)
        
        return {
            "matches": matches,
            "total": len(matches),
            "universe_size": len(universe),
            "filters": {
                "days_recent": days_recent,
                "min_reliability": min_reliability,
                "direction": direction,
            },
            "updated_at": datetime.now().isoformat(),
        }
    
    except Exception as e:
        logger.exception(f"[patterns] scan fail: {e}")
        raise HTTPException(500, str(e))
