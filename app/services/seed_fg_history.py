"""
Seed script: tạo dữ liệu F&G lịch sử fake để demo chart.

Cách dùng:
    cd C:\\vpastock\\vpastock-backend-v1\\vpastock-backend
    python -m app.services.seed_fg_history

Tạo ~120 snapshot trải dài 60 ngày qua (mỗi 12 giờ), mô phỏng F&G dao động
quanh trung tâm 50 với biên độ ±25, có trend nhẹ.

Không xoá data có sẵn - chỉ thêm. Nếu muốn reset hoàn toàn, xoá DB trước:
    del data\\fg_history.db
"""
from __future__ import annotations
import math
import random
import sqlite3
from datetime import datetime, timedelta
from app.services.fg_history import _DB_PATH, init_db


def _label_for(score: float) -> tuple[str, str]:
    if score < 25: return "Sợ hãi cực độ", "😱"
    if score < 45: return "Sợ hãi", "😨"
    if score < 55: return "Trung tính", "😐"
    if score < 75: return "Tham lam", "😏"
    return "Tham lam cực độ", "🤑"


def seed(days: int = 60, points_per_day: int = 2) -> int:
    """Generate `days * points_per_day` snapshots evenly spaced.
    
    Score uses sine wave + random noise:
        score(t) = 50 + 20*sin(t/period) + noise(±5)
    """
    init_db()
    
    now = datetime.utcnow()
    total = days * points_per_day
    interval_hours = 24 / points_per_day
    period = 14 * points_per_day  # full cycle ~14 ngày
    
    rows = []
    base_vnindex = 1850
    
    for i in range(total):
        # Time (oldest first)
        offset_hours = (total - 1 - i) * interval_hours
        ts = now - timedelta(hours=offset_hours)
        
        # Wave + noise
        t = i
        score = 50 + 20 * math.sin(t / period * 2 * math.pi) + random.uniform(-5, 5)
        score = round(max(5, min(95, score)), 1)
        
        # Derived
        label, _ = _label_for(score)
        vnindex_value = round(base_vnindex + (score - 50) * 4 + random.uniform(-15, 15), 2)
        vnindex_ma200 = round(base_vnindex - 50, 2)
        rsi = round(max(20, min(80, score + random.uniform(-8, 8))), 1)
        pct_above_ma = round((vnindex_value - vnindex_ma200) / vnindex_ma200 * 100, 2)
        vol_ratio = round(0.7 + (score - 30) / 100 + random.uniform(-0.15, 0.15), 2)
        atr_ratio = round(0.6 + (60 - score) / 100 + random.uniform(-0.1, 0.1), 2)
        momentum_5d = round((score - 50) / 8 + random.uniform(-1, 1), 2)
        
        rows.append((
            ts.isoformat(), score, label,
            vnindex_value, vnindex_ma200,
            rsi, pct_above_ma, vol_ratio, atr_ratio, momentum_5d,
        ))
    
    # Insert (bypass dedupe của save_snapshot)
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.executemany(
            """
            INSERT INTO fg_history (
                timestamp, score, label,
                vnindex_value, vnindex_ma200,
                rsi, pct_above_ma, vol_ratio, atr_ratio, momentum_5d
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )
        conn.commit()
        print(f"✅ Đã chèn {len(rows)} snapshot vào {_DB_PATH}")
        print(f"   Khoảng thời gian: {days} ngày qua")
        print(f"   Mật độ: {points_per_day} điểm/ngày")
        
        # Stats
        total_rows = conn.execute("SELECT COUNT(*) FROM fg_history").fetchone()[0]
        print(f"   Tổng số dòng trong DB: {total_rows}")
    finally:
        conn.close()
    
    return len(rows)


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    ppd = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    seed(days=days, points_per_day=ppd)
