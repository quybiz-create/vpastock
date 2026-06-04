"""
Portfolio API - Phase 12

Endpoints:
- GET    /api/portfolio                → list all positions (kèm P/L)
- GET    /api/portfolio?status=open    → chỉ open positions
- POST   /api/portfolio                → thêm lệnh
- POST   /api/portfolio/{id}/close     → đóng lệnh
- DELETE /api/portfolio/{id}           → xóa
- PATCH  /api/portfolio/{id}           → update note
- GET    /api/portfolio/summary        → dashboard
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field
from loguru import logger

router = APIRouter(tags=["portfolio"])


class AddPositionReq(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)
    quantity: int = Field(..., gt=0)
    entry_price: float = Field(..., gt=0)
    entry_date: str = Field(..., min_length=10, max_length=10, description="YYYY-MM-DD")
    note: str = Field("", max_length=300)


class ClosePositionReq(BaseModel):
    exit_price: float = Field(..., gt=0)
    exit_date: str = Field(..., min_length=10, max_length=10)


class UpdateNoteReq(BaseModel):
    note: str = Field(..., max_length=300)


@router.get("")
async def list_portfolio(status: Optional[str] = Query(None, description="'open' / 'closed' / null=all")):
    """Lấy danh sách positions kèm P/L."""
    from app.services.portfolio import list_positions, enrich_with_pl
    try:
        if status and status not in ("open", "closed"):
            raise HTTPException(400, "status phải là 'open' hoặc 'closed'")
        positions = list_positions(status=status)
        enriched = await enrich_with_pl(positions)
        return {
            "count": len(enriched),
            "items": enriched,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"portfolio list error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.post("")
async def create_position(req: AddPositionReq):
    """Thêm lệnh mới."""
    from app.services.portfolio import add_position
    try:
        return add_position(req.symbol, req.quantity, req.entry_price, req.entry_date, req.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception(f"portfolio add error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.post("/{position_id}/close")
async def close_position_endpoint(
    req: ClosePositionReq,
    position_id: int = Path(..., ge=1),
):
    """Đóng lệnh (realize P/L)."""
    from app.services.portfolio import close_position
    try:
        result = close_position(position_id, req.exit_price, req.exit_date)
        if not result:
            raise HTTPException(404, f"Lệnh {position_id} không tồn tại")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception(f"portfolio close {position_id} error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.delete("/{position_id}")
async def delete_position_endpoint(position_id: int = Path(..., ge=1)):
    from app.services.portfolio import delete_position
    try:
        if not delete_position(position_id):
            raise HTTPException(404, f"Lệnh {position_id} không tồn tại")
        return {"deleted": True, "position_id": position_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"portfolio delete {position_id} error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.patch("/{position_id}")
async def update_position_note(
    req: UpdateNoteReq,
    position_id: int = Path(..., ge=1),
):
    """Cập nhật ghi chú."""
    from app.services.portfolio import update_note
    try:
        result = update_note(position_id, req.note)
        if not result:
            raise HTTPException(404, f"Lệnh {position_id} không tồn tại")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"portfolio update {position_id} error: {e}")
        raise HTTPException(500, f"Failed: {e}")


@router.get("/summary")
async def get_portfolio_summary():
    """Dashboard summary."""
    from app.services.portfolio import get_summary
    try:
        return await get_summary()
    except Exception as e:
        logger.exception(f"portfolio summary error: {e}")
        raise HTTPException(500, f"Failed: {e}")
