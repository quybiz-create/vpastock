"""
Wyckoff Scanner - Phase 9D

Quét top 200 mã VN tìm những mã có setup Wyckoff rõ ràng.
Sử dụng background task với job_id để frontend poll progress.

Workflow:
1. POST /scan/start → tạo job_id, kick off background scan
2. GET  /scan/status/{job_id} → poll % progress
3. GET  /scan/results/{job_id} → lấy kết quả khi done

Job state in-memory (single instance backend).
"""
from __future__ import annotations
import asyncio
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from loguru import logger


# ============================================================
# Top 200 mã - tổng hợp từ SECTOR_STOCKS đã có + bổ sung
# Chọn các mã VN30, VN50, VN70 + thanh khoản cao
# ============================================================
TOP_200_SYMBOLS = [
    # Banks (18)
    "VCB", "BID", "CTG", "TCB", "MBB", "VPB", "ACB", "HDB", "STB", "TPB",
    "VIB", "SHB", "LPB", "EIB", "MSB", "OCB", "NAB", "VAB",
    # Real Estate (18)
    "VHM", "VIC", "VRE", "NVL", "KDH", "DXG", "PDR", "NLG", "DIG", "CEO",
    "KBC", "ITA", "HDC", "AGG", "HDG", "SCR", "TCH", "HPX",
    # Steel + Materials (12)
    "HPG", "HSG", "NKG", "POM", "TVN", "TLH", "VGS", "SMC", "VPG",
    "VCG", "CTD", "HT1",
    # Construction (10)
    "HBC", "HUT", "C4G", "LCG", "FCN", "BCC", "BMP", "VGC", "PHC", "VLB",
    # Food & Beverage (14)
    "VNM", "MSN", "SAB", "MCH", "VHC", "SBT", "DBC", "KDC", "ANV", "BAF",
    "ASM", "FMC", "PAN", "TNG",
    # Oil & Gas (9)
    "GAS", "PLX", "BSR", "OIL", "PVD", "PVS", "PVT", "PVC", "PVB",
    # Retail (6)
    "MWG", "FRT", "DGW", "PNJ", "PET", "SVC",
    # Technology (7)
    "FPT", "CMG", "ELC", "ITD", "SAM", "SGT", "ICT",
    # Securities (15)
    "SSI", "VCI", "VND", "HCM", "SHS", "VIX", "FTS", "MBS", "BVS", "AGR",
    "CTS", "ORS", "TVS", "BSI", "APS",
    # Utilities (11)
    "POW", "REE", "NT2", "GEG", "PC1", "VSH", "TBC", "TMP", "CHP", "SBA",
    "GEX",
    # Industrial / Logistics (8)
    "GMD", "VSC", "HAH", "VOS", "VTP", "PHP", "SCS", "ACV",
    # Insurance (6)
    "BVH", "BIC", "MIG", "VNR", "PVI", "BMI",
    # Health Care (7)
    "DHG", "IMP", "DBD", "DCL", "DMC", "PMC", "TRA",
    # Aviation / Travel (5)
    "VJC", "HVN", "OCH", "VTR", "DAH",
    # Chemicals (7)
    "DCM", "DPM", "DGC", "BFC", "VAF", "CSV", "LAS",
    # Auto / Tires (6)
    "TMT", "HAX", "VEA", "DRC", "SRC", "CSM",
    # Apparel / Consumer (8)
    "GIL", "TCM", "STK", "MSH", "EVE", "ADS", "TNG", "VGT",
    # Misc large caps / liquidity (16)
    "VEF", "BCM", "LIX", "TLG", "DGW", "PHN", "PTL", "VPI",
    "DPG", "LTG", "DAG", "GMC", "FCM", "SBT", "BAF", "DXS",
    # Others (15) 
    "REE", "GTN", "VND", "AAA", "DHA", "TLG", "VHC", "RAL",
    "DCM", "MPC", "FLC", "ROS", "AMD", "ART", "KLF",
]
# Dedupe
TOP_200_SYMBOLS = list(dict.fromkeys(TOP_200_SYMBOLS))


# In-memory job store {job_id: {status, progress, results, started_at, ...}}
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOB_TTL = 30 * 60   # 30 phút


def _cleanup_old_jobs():
    """Xóa các job cũ hơn TTL."""
    now = time.time()
    to_del = [jid for jid, j in _JOBS.items() if (now - j.get("started_at", 0)) > _JOB_TTL]
    for jid in to_del:
        _JOBS.pop(jid, None)


async def _scan_single(symbol: str) -> Optional[Dict[str, Any]]:
    """Phân tích Wyckoff cho 1 symbol. Trả None nếu setup='none' hoặc lỗi."""
    try:
        from app.data.vnstock_client import vnstock_client
        from app.services.wyckoff import analyze_wyckoff
        
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
        df = await asyncio.wait_for(
            vnstock_client.get_history(symbol, start=start, end=end),
            timeout=8.0,
        )
        if df is None or df.empty or len(df) < 50:
            return None
        
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
        
        result = analyze_wyckoff(bars, period=200)
        setup = result.get("setup")
        if setup == "none":
            return None
        
        # Compact result for scanner table
        last_price = bars[-1]["close"]
        tr = result.get("trading_range") or {}
        events = result.get("events", [])
        # Đếm event types
        event_types = list(set(e["type"] for e in events))
        # Last event (gần nhất theo index)
        last_event = max(events, key=lambda e: e["index"]) if events else None
        
        return {
            "symbol": symbol,
            "setup": setup,
            "phase": result.get("phase"),
            "confidence": result.get("confidence", 0),
            "price": round(last_price, 2),
            "tr_high": tr.get("high"),
            "tr_low": tr.get("low"),
            "tr_mid": tr.get("mid"),
            "tr_range_pct": tr.get("range_pct"),
            "tr_bars": tr.get("bars_count"),
            "pre_trend": result.get("pre_trend"),
            "events_count": len(events),
            "event_types": event_types,
            "last_event": last_event["type"] if last_event else None,
            "suggestion": result.get("suggestion", "")[:140],
        }
    except asyncio.TimeoutError:
        logger.debug(f"[scanner] timeout {symbol}")
        return None
    except SystemExit:
        # vnstock rate limit - không raise, chỉ log warning và return None
        # Worker sẽ sleep dài hơn ở batch tiếp theo
        logger.warning(f"[scanner] rate limit hit at {symbol}, skipping")
        return "RATE_LIMITED"
    except Exception as e:
        logger.debug(f"[scanner] skip {symbol}: {e}")
        return None


async def _scan_worker(job_id: str, symbols: List[str], batch_size: int = 3):
    """Background worker quét từng batch symbol và update progress."""
    job = _JOBS[job_id]
    job["status"] = "running"
    total = len(symbols)
    completed = 0
    found = []
    
    try:
        for batch_start in range(0, total, batch_size):
            batch = symbols[batch_start:batch_start + batch_size]
            # Chạy song song trong batch, sequential giữa batch để tránh rate limit
            tasks = [_scan_single(sym) for sym in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            hit_rate_limit = False
            for sym, r in zip(batch, results):
                completed += 1
                if isinstance(r, Exception):
                    continue
                if r == "RATE_LIMITED":
                    hit_rate_limit = True
                    continue
                if r is not None:
                    found.append(r)
            
            # Update progress
            job["progress"] = round(completed / total * 100, 1)
            job["completed"] = completed
            job["found_count"] = len(found)
            
            # Nếu hit rate limit → sleep dài 30s
            if hit_rate_limit:
                logger.warning(f"[scanner] rate limit hit, sleeping 30s...")
                job["status"] = "rate_limited_pause"
                await asyncio.sleep(30)
                job["status"] = "running"
            
            # Phase 9D fix: Sleep 1.8s giữa các batch để tránh rate limit
            # 3 mã/batch × ~40 batch/phút = 120 req/phút (vẫn quá → cần chậm hơn)
            # Sleep 1.8s → max ~33 batch/phút = ~100 req/phút (an toàn)
            # Thực tế ~50 req/phút vì có overhead
            await asyncio.sleep(1.8)
        
        # Sort kết quả: ưu tiên Phase D/E + confidence cao
        phase_priority = {"E": 5, "D": 4, "C": 3, "B": 2, "A": 1, "none": 0}
        found.sort(key=lambda x: (phase_priority.get(x.get("phase"), 0), x.get("confidence", 0)), reverse=True)
        
        job["status"] = "done"
        job["results"] = found
        job["completed_at"] = time.time()
        job["found_count"] = len(found)
        logger.info(f"[scanner] done {job_id}: scanned {total}, found {len(found)}")
    except Exception as e:
        logger.exception(f"[scanner] worker {job_id} fail: {e}")
        job["status"] = "error"
        job["error"] = str(e)[:200]
        job["completed_at"] = time.time()


def start_scan(symbols: Optional[List[str]] = None) -> str:
    """Khởi tạo job mới, kick off background task. Trả về job_id."""
    _cleanup_old_jobs()
    job_id = str(uuid.uuid4())[:12]
    syms = symbols if symbols else TOP_200_SYMBOLS
    _JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress": 0.0,
        "completed": 0,
        "total": len(syms),
        "found_count": 0,
        "results": [],
        "started_at": time.time(),
        "symbols_total": len(syms),
    }
    # Kick off background task
    asyncio.create_task(_scan_worker(job_id, syms))
    return job_id


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Get current status (without results để tránh payload lớn)."""
    job = _JOBS.get(job_id)
    if not job:
        return None
    elapsed = time.time() - job["started_at"]
    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "completed": job["completed"],
        "total": job["total"],
        "found_count": job["found_count"],
        "elapsed_sec": round(elapsed, 1),
        "error": job.get("error"),
    }


def get_job_results(job_id: str) -> Optional[Dict[str, Any]]:
    """Get full results khi job done."""
    job = _JOBS.get(job_id)
    if not job:
        return None
    return {
        "job_id": job_id,
        "status": job["status"],
        "total": job["total"],
        "completed": job["completed"],
        "found_count": job["found_count"],
        "results": job.get("results", []),
        "elapsed_sec": round(time.time() - job["started_at"], 1),
        "error": job.get("error"),
    }
