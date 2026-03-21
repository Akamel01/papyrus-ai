"""DLQ routes: list, retry, skip."""
from fastapi import APIRouter, HTTPException, Depends
from auth import require_operator, TokenPayload
import db_reader
from audit_logger import log_audit

router = APIRouter()


@router.get("")
async def list_dlq(status: str = "pending", _user: TokenPayload = Depends(require_operator)):
    return db_reader.get_dlq_items(status)


@router.post("/{dlq_id}/retry")
async def retry_item(dlq_id: int, user: TokenPayload = Depends(require_operator)):
    try:
        db_reader.retry_dlq_item(dlq_id)
        log_audit(user.sub, "dlq.retry", {"dlq_id": dlq_id})
        return {"ok": True, "new_status": "retried"}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{dlq_id}/skip")
async def skip_item(dlq_id: int, user: TokenPayload = Depends(require_operator)):
    db_reader.skip_dlq_item(dlq_id)
    log_audit(user.sub, "dlq.skip", {"dlq_id": dlq_id})
    return {"ok": True}
