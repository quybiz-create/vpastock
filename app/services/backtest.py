"""
Wyckoff Backtest - Phase 13

Mô phỏng các chiến lược Wyckoff trên 1 mã trong N năm để tính:
- Win rate
- Avg gain / loss per trade
- Max drawdown
- Sharpe ratio (approx)
- Total return vs Buy & Hold
- Equity curve

3 CHIẾN LƯỢC:
A) classic: Mua tại Spring/LPS, bán tại UTAD/LPSY (Wyckoff classic)
B) phase_d: Mua khi Phase chuyển sang D Accumulation, bán khi Phase D Distribution
C) setup_conf: Mua setup=accumulation conf>=70%, bán khi setup chuyển distribution

CHẠY THẾ NÀO:
- Walk-forward: tại mỗi bar t, dùng bars[:t] để tính Wyckoff
- Phát tín hiệu entry/exit theo strategy
- Mô phỏng position: vào lệnh, theo dõi, đóng khi có exit signal
- Tính P/L mỗi trade
- Có thể có nhiều trade trong period

Cache 30 phút per (symbol, strategy, period_days).
"""
from __future__ import annotations
import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger
import math


_BACKTEST_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = 30 * 60   # 30 phút


def _analyze_lite(bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Wrapper analyze_wyckoff, return compact state. Never returns None."""
    DEFAULT = {"setup": "none", "phase": "none", "confidence": 0, "event_types": []}
    if not bars or len(bars) < 50:
        return DEFAULT
    try:
        from app.services.wyckoff import analyze_wyckoff
        result = analyze_wyckoff(bars, period=200)
        if not result or not isinstance(result, dict):
            return DEFAULT
        events = result.get("events") or []
        return {
            "setup": result.get("setup") or "none",
            "phase": result.get("phase") or "none",
            "confidence": result.get("confidence") or 0,
            "event_types": list(set(e.get("type", "") for e in events if e and isinstance(e, dict))),
            "tr_high": (result.get("trading_range") or {}).get("high"),
            "tr_low": (result.get("trading_range") or {}).get("low"),
        }
    except Exception as ex:
        from loguru import logger
        logger.debug(f"[backtest] _analyze_lite skip: {ex}")
        return DEFAULT


def _check_entry_signal(state: Optional[Dict[str, Any]], strategy: str) -> bool:
    """Kiểm tra có tín hiệu entry không."""
    if not state:
        return False
    setup = state.get("setup")
    phase = state.get("phase")
    conf = state.get("confidence", 0)
    events = set(state.get("event_types", []))
    
    if strategy == "classic":
        # Mua khi có Spring hoặc LPS (accumulation only)
        return setup == "accumulation" and bool(events & {"Spring", "LPS", "ST-Spring"})
    
    elif strategy == "phase_d":
        # Mua khi Phase D Accumulation (hoặc Phase C nếu đã có Spring/LPS)
        if setup == "accumulation":
            if phase == "D":
                return True
            # Phase C với Spring/LPS đã xuất hiện → cũng OK vào
            if phase == "C" and bool(events & {"Spring", "LPS", "ST-Spring"}):
                return True
        return False
    
    elif strategy == "setup_conf":
        # Mua khi setup=accumulation conf >= 60% (loose hơn)
        return setup == "accumulation" and conf >= 0.60
    
    return False


def _check_exit_signal(state: Optional[Dict[str, Any]], strategy: str) -> bool:
    """Kiểm tra có tín hiệu exit không."""
    if not state:
        return False
    setup = state.get("setup")
    phase = state.get("phase")
    events = set(state.get("event_types", []))
    
    if strategy == "classic":
        # Bán khi UTAD/LPSY xuất hiện hoặc chuyển distribution
        return (setup == "distribution" and bool(events & {"UTAD", "LPSY"})) or \
               (setup == "distribution" and phase in ("D", "E"))
    
    elif strategy == "phase_d":
        # Bán khi setup chuyển distribution (any phase) hoặc UTAD xuất hiện
        if setup == "distribution":
            return True
        # Hoặc khi accumulation phase E (đã markup mạnh - take profit)
        if setup == "accumulation" and phase == "E":
            return True
        return False
    
    elif strategy == "setup_conf":
        # Bán khi chuyển distribution
        return setup == "distribution"
    
    return False


def _run_backtest_simulation(
    bars: List[Dict[str, Any]],
    strategy: str,
    initial_capital: float = 100000000,   # 100tr VND
    warmup_bars: int = 250,                # cần ~1 năm history để có Wyckoff signal
    recompute_every: int = 3,              # tính Wyckoff mỗi N bars
    fee_rate: float = 0.0015,              # 0.15% phí giao dịch (mua + bán)
) -> Dict[str, Any]:
    """Mô phỏng backtest. Trả về dict đầy đủ kết quả. NEVER returns None."""
    try:
        return _run_backtest_simulation_inner(bars, strategy, initial_capital, warmup_bars, recompute_every, fee_rate)
    except Exception as e:
        logger.exception(f"[backtest] simulation inner crash: {e}")
        return {
            "error": f"Simulation crash: {type(e).__name__}: {str(e)[:200]}",
            "summary": {
                "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "total_return_pct": 0, "total_net_pl": 0, "avg_win_pct": 0,
                "avg_loss_pct": 0, "best_trade_pct": 0, "worst_trade_pct": 0,
                "avg_hold_days": 0, "max_drawdown_pct": 0, "sharpe_ratio": 0,
                "bh_return_pct": 0, "alpha_pct": 0, "initial_capital": initial_capital,
                "final_equity": initial_capital,
            },
            "trades": [],
            "equity_curve": [],
            "debug": {"setup_counts": {}, "phase_counts": {}, "checks_total": 0, "error": str(e)[:200]},
        }


def _run_backtest_simulation_inner(
    bars: List[Dict[str, Any]],
    strategy: str,
    initial_capital: float = 100000000,
    warmup_bars: int = 250,
    recompute_every: int = 3,
    fee_rate: float = 0.0015,
) -> Dict[str, Any]:
    """Internal simulation - exception này được wrapper catch."""
    n = len(bars)
    if n < warmup_bars + 30:
        return {
            "error": f"Không đủ dữ liệu (cần ít nhất {warmup_bars + 30} bars, có {n})",
            "trades": [],
        }
    
    # State
    cash = initial_capital
    position = None   # None hoặc dict{entry_bar, entry_price, qty, entry_date}
    trades: List[Dict[str, Any]] = []
    equity_curve: List[Dict[str, Any]] = []
    last_state: Optional[Dict[str, Any]] = None
    # Phase 13 debug counters
    setup_counts = {"accumulation": 0, "distribution": 0, "none": 0}
    phase_counts = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "none": 0}
    checks_total = 0
    
    # Buy & Hold reference
    bh_entry_price = bars[warmup_bars]["close"]
    bh_qty = math.floor(initial_capital / bh_entry_price / 100) * 100  # lot 100
    
    for i in range(warmup_bars, n):
        bar = bars[i]
        price = bar["close"]
        date = bar["time"]
        
        # Tính Wyckoff state mỗi `recompute_every` bars (tránh chậm)
        if last_state is None or (i % recompute_every == 0):
            window = bars[max(0, i - 250):i + 1]
            last_state = _analyze_lite(window) or {"setup": "none", "phase": "none", "confidence": 0, "event_types": []}
            checks_total += 1
            s = last_state.get("setup") or "none"
            p = last_state.get("phase") or "none"
            setup_counts[s] = setup_counts.get(s, 0) + 1
            phase_counts[p] = phase_counts.get(p, 0) + 1
        
        # Position management
        if position is None:
            # Check entry
            if _check_entry_signal(last_state, strategy):
                # Mua hết tiền (theo lot 100)
                qty = math.floor(cash / price / 100) * 100
                if qty > 0:
                    cost = qty * price * (1 + fee_rate)
                    if cost <= cash:
                        position = {
                            "entry_bar": i,
                            "entry_price": price,
                            "qty": qty,
                            "entry_date": date,
                            "entry_state": dict(last_state),
                        }
                        cash -= cost
        else:
            # Check exit
            if _check_exit_signal(last_state, strategy):
                proceeds = position["qty"] * price * (1 - fee_rate)
                cash += proceeds
                gross_pl = (price - position["entry_price"]) * position["qty"]
                net_pl = proceeds - (position["qty"] * position["entry_price"] * (1 + fee_rate))
                pl_pct = (price - position["entry_price"]) / position["entry_price"] * 100
                hold_days = i - position["entry_bar"]
                
                trades.append({
                    "entry_date": position["entry_date"],
                    "exit_date": date,
                    "entry_price": round(position["entry_price"], 2),
                    "exit_price": round(price, 2),
                    "qty": position["qty"],
                    "gross_pl": round(gross_pl, 0),
                    "net_pl": round(net_pl, 0),
                    "pl_pct": round(pl_pct, 2),
                    "hold_days": hold_days,
                    "entry_phase": (position.get("entry_state") or {}).get("phase"),
                    "exit_phase": (last_state or {}).get("phase"),
                })
                position = None
        
        # Equity curve
        current_equity = cash
        if position is not None:
            current_equity += position["qty"] * price
        equity_curve.append({
            "date": date,
            "equity": round(current_equity, 0),
            "bh_equity": round(bh_qty * price, 0),
            "in_position": position is not None,
        })
    
    # Đóng position còn open (theo giá cuối)
    if last_state is None:
        last_state = {"setup": "none", "phase": "none"}
    if position is not None:
        last_bar = bars[-1]
        price = last_bar["close"]
        proceeds = position["qty"] * price * (1 - fee_rate)
        cash += proceeds
        gross_pl = (price - position["entry_price"]) * position["qty"]
        net_pl = proceeds - (position["qty"] * position["entry_price"] * (1 + fee_rate))
        pl_pct = (price - position["entry_price"]) / position["entry_price"] * 100
        trades.append({
            "entry_date": position["entry_date"],
            "exit_date": last_bar["time"],
            "entry_price": round(position["entry_price"], 2),
            "exit_price": round(price, 2),
            "qty": position["qty"],
            "gross_pl": round(gross_pl, 0),
            "net_pl": round(net_pl, 0),
            "pl_pct": round(pl_pct, 2),
            "hold_days": len(bars) - 1 - position["entry_bar"],
            "entry_phase": (position.get("entry_state") or {}).get("phase"),
            "exit_phase": (last_state or {}).get("phase"),
            "still_open": True,
        })
    
    stats = _compute_stats(
        initial_capital, cash, trades, equity_curve, bh_entry_price, bars[-1]["close"], bh_qty,
    )
    # Phase 13: Track signal stats (computed during main loop)
    stats["debug"] = {
        "setup_counts": setup_counts,
        "phase_counts": phase_counts,
        "checks_total": checks_total,
        "warmup_bars": warmup_bars,
    }
    return stats


def _compute_stats(
    initial_capital: float,
    final_cash: float,
    trades: List[Dict[str, Any]],
    equity_curve: List[Dict[str, Any]],
    bh_entry_price: float,
    bh_last_price: float,
    bh_qty: int,
) -> Dict[str, Any]:
    """Tổng hợp metric."""
    total_trades = len(trades)
    wins = [t for t in trades if t["net_pl"] > 0]
    losses = [t for t in trades if t["net_pl"] <= 0]
    win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0
    
    total_net_pl = sum(t["net_pl"] for t in trades)
    total_return_pct = (final_cash - initial_capital) / initial_capital * 100
    
    avg_win = sum(t["pl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pl_pct"] for t in losses) / len(losses) if losses else 0
    best_trade = max((t["pl_pct"] for t in trades), default=0)
    worst_trade = min((t["pl_pct"] for t in trades), default=0)
    avg_hold = sum(t["hold_days"] for t in trades) / total_trades if total_trades > 0 else 0
    
    # Max drawdown từ equity curve
    max_dd = 0.0
    peak = initial_capital
    for pt in equity_curve:
        eq = pt["equity"]
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    
    # Buy & Hold return
    bh_final = bh_qty * bh_last_price
    bh_return_pct = (bh_final - bh_qty * bh_entry_price) / (bh_qty * bh_entry_price) * 100 if bh_qty > 0 else 0
    alpha = total_return_pct - bh_return_pct
    
    # Sharpe đơn giản (daily returns std)
    if len(equity_curve) > 30:
        daily_rets = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]["equity"]
            cur = equity_curve[i]["equity"]
            if prev > 0:
                daily_rets.append((cur - prev) / prev)
        if daily_rets:
            mean_ret = sum(daily_rets) / len(daily_rets)
            variance = sum((r - mean_ret) ** 2 for r in daily_rets) / len(daily_rets)
            std = math.sqrt(variance) if variance > 0 else 0
            # Annualize: sqrt(252)
            sharpe = (mean_ret / std * math.sqrt(252)) if std > 0 else 0
        else:
            sharpe = 0
    else:
        sharpe = 0
    
    return {
        "summary": {
            "total_trades": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "total_return_pct": round(total_return_pct, 2),
            "total_net_pl": round(total_net_pl, 0),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "best_trade_pct": round(best_trade, 2),
            "worst_trade_pct": round(worst_trade, 2),
            "avg_hold_days": round(avg_hold, 1),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 2),
            "bh_return_pct": round(bh_return_pct, 2),
            "alpha_pct": round(alpha, 2),
            "initial_capital": initial_capital,
            "final_equity": round(final_cash, 0),
        },
        "trades": trades,
        "equity_curve": equity_curve,
    }


async def run_backtest(
    symbol: str,
    strategy: str = "phase_d",
    period_years: int = 2,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Chạy backtest cho 1 mã.
    
    strategy: 'classic' / 'phase_d' / 'setup_conf'
    period_years: 1 / 2 / 5
    """
    symbol = symbol.upper().strip()
    valid_strategies = {"classic", "phase_d", "setup_conf"}
    if strategy not in valid_strategies:
        raise ValueError(f"strategy must be one of {valid_strategies}")
    
    cache_key = f"{symbol}:{strategy}:{period_years}"
    now = time.time()
    
    if not force_refresh:
        cached = _BACKTEST_CACHE.get(cache_key)
        if cached and (now - cached["at"]) < _CACHE_TTL:
            result = dict(cached["data"])
            result["cached"] = True
            return result
    
    # Load history
    try:
        from app.data.vnstock_client import vnstock_client
        days_back = period_years * 365 + 400   # +400 ngày để có warmup
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        df = await vnstock_client.get_history(symbol, start=start, end=end)
        if df is None or df.empty:
            return {"error": f"Không lấy được dữ liệu cho {symbol}", "symbol": symbol}
        
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
        
        if len(bars) < 300:
            return {
                "error": f"Không đủ dữ liệu ({len(bars)} bars, cần >=300)",
                "symbol": symbol,
                "bars_count": len(bars),
            }
        
        logger.info(f"[backtest] {symbol} strategy={strategy} years={period_years} bars={len(bars)}")
        
        # Run simulation in thread to avoid blocking
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                _run_backtest_simulation,
                bars, strategy,
            )
        except Exception as sim_e:
            logger.exception(f"[backtest] simulation crash {symbol}: {sim_e}")
            return {
                "error": f"Simulation failed: {str(sim_e)[:200]}",
                "symbol": symbol,
                "strategy": strategy,
            }
        
        # Safety: result must be dict
        if not result or not isinstance(result, dict):
            return {
                "error": "Simulation returned no result",
                "symbol": symbol,
                "strategy": strategy,
            }
        
        result["symbol"] = symbol
        result["strategy"] = strategy
        result["period_years"] = period_years
        result["bars_count"] = len(bars)
        result["updated_at"] = datetime.now().isoformat()
        
        _BACKTEST_CACHE[cache_key] = {"at": now, "data": result}
        return result
    
    except SystemExit:
        return {"error": "vnstock rate limit, vui lòng chờ vài phút", "symbol": symbol}
    except Exception as e:
        logger.exception(f"[backtest] {symbol} fail: {e}")
        return {"error": str(e)[:200], "symbol": symbol}


def get_strategy_info() -> List[Dict[str, str]]:
    """Mô tả ngắn các chiến lược cho UI."""
    return [
        {
            "key": "classic",
            "name": "Classic Wyckoff",
            "desc": "Mua Spring/LPS → Bán UTAD/LPSY. Entry timing tốt nhất nhưng ít signal.",
        },
        {
            "key": "phase_d",
            "name": "Phase D Trading",
            "desc": "Mua khi Phase D Accumulation → Bán khi Phase D Distribution. Cân bằng.",
        },
        {
            "key": "setup_conf",
            "name": "Setup + Confidence",
            "desc": "Mua khi setup=Accumulation và confidence≥70% → Bán khi chuyển Distribution. Nhiều signal hơn.",
        },
    ]
