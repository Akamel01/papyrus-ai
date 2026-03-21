"""Audit routes: read audit log with filters."""
from fastapi import APIRouter, Depends, Query
from auth import require_admin, TokenPayload
from audit_logger import read_audit

router = APIRouter()


@router.get("")
async def get_audit(
    user: str = Query(None),
    action: str = Query(None),
    from_ts: str = Query(None, alias="from"),
    to_ts: str = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    _admin: TokenPayload = Depends(require_admin),
):
    return read_audit(user=user, action=action, from_ts=from_ts, to_ts=to_ts, page=page)
