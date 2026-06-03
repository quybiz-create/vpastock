"""
Smart Alerts API - Phase 11

Endpoints:
- GET    /api/alerts                  → list all alerts
- POST   /api/alerts                  → create alert  
- DELETE /api/alerts/{id}             → delete alert
- PATCH  /api/alerts/{id}/toggle      → toggle enable/disable
- POST   /api/alerts/{id}/test        → trigger check ngay (test)
- GET    /api/alerts/{id}/history     → log của 1 alert
- GET    /api/alerts/history/recent   → log tổng gần đây
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Path, Body
from pydantic import BaseModel, Field
from loguru import logger

router = APIRouter(tags=["alerts"])


class CreateAlertReq(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)
    alert_type: str = Field(..., description="phase_change, spring, utad, phase_d, breakout, sos_sow, any")
    note: str = Field("", max_length=200)


@router.get("")
async def get_alerts(enabled_only: bool = False):
    """Lấy danh sách tất cả alerts."""
    from app.services.alert_manager import list_alerts
    try:
        items = list_alerts(enabled_only=enabled_only)
        return {
            "count": len(items),
            "items": items,
        }
    except Exception as e:
        logger.exception(f"alerts list error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.post("")
async def create_new_alert(req: CreateAlertReq):
    """Tạo alert mới."""
    from app.services.alert_manager import create_alert
    try:
        item = create_alert(req.symbol, req.alert_type, req.note)
        return item
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception(f"alerts create error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.delete("/{alert_id}")
async def delete_one_alert(alert_id: int = Path(..., ge=1)):
    """Xóa 1 alert (+ history)."""
    from app.services.alert_manager import delete_alert
    try:
        if not delete_alert(alert_id):
            raise HTTPException(404, f"Alert {alert_id} không tồn tại")
        return {"deleted": True, "alert_id": alert_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"alerts delete {alert_id} error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.patch("/{alert_id}/toggle")
async def toggle_one_alert(alert_id: int = Path(..., ge=1)):
    """Bật/tắt alert."""
    from app.services.alert_manager import toggle_alert
    try:
        item = toggle_alert(alert_id)
        if not item:
            raise HTTPException(404, f"Alert {alert_id} không tồn tại")
        return item
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"alerts toggle {alert_id} error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.post("/{alert_id}/test")
async def test_one_alert(alert_id: int = Path(..., ge=1)):
    """Trigger check ngay (không đợi 15 phút). Dùng để test alert."""
    from app.services.alert_manager import get_alert, check_one_alert
    try:
        alert = get_alert(alert_id)
        if not alert:
            raise HTTPException(404, f"Alert {alert_id} không tồn tại")
        n_triggered = await check_one_alert(alert)
        return {
            "alert_id": alert_id,
            "triggered_events": n_triggered,
            "message": f"Đã check. Trigger {n_triggered} sự kiện." if n_triggered else "Đã check. Chưa có sự kiện mới.",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"alerts test {alert_id} error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.get("/{alert_id}/history")
async def get_one_alert_history(alert_id: int = Path(..., ge=1), limit: int = 50):
    """Lấy log lịch sử trigger của 1 alert."""
    from app.services.alert_manager import get_alert, get_alert_history
    try:
        alert = get_alert(alert_id)
        if not alert:
            raise HTTPException(404, f"Alert {alert_id} không tồn tại")
        items = get_alert_history(alert_id, limit=limit)
        return {
            "alert_id": alert_id,
            "symbol": alert.get("symbol"),
            "count": len(items),
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"alerts history {alert_id} error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.get("/history/recent")
async def get_recent_alerts_history(limit: int = 30):
    """Lấy log tổng tất cả alerts gần nhất (dashboard)."""
    from app.services.alert_manager import get_recent_history
    try:
        items = get_recent_history(limit=limit)
        return {"count": len(items), "items": items}
    except Exception as e:
        logger.exception(f"alerts recent history error: {e}")
        raise HTTPException(500, f"Failed: {e}")
