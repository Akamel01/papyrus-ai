"""Qdrant routes: stats, snapshot with safeguards."""
from fastapi import APIRouter, HTTPException, Depends
from auth import require_viewer, require_admin, TokenPayload
import qdrant_client as qc
from audit_logger import log_audit

router = APIRouter()


@router.get("/stats")
async def get_stats(_user: TokenPayload = Depends(require_viewer)):
    return await qc.get_stats()


@router.get("/snapshots")
async def list_snapshots(_user: TokenPayload = Depends(require_admin)):
    return await qc.list_snapshots()


@router.post("/snapshot")
async def create_snapshot(user: TokenPayload = Depends(require_admin)):
    try:
        result = await qc.trigger_snapshot()
        log_audit(user.sub, "qdrant.snapshot", result)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/snapshots/{snapshot_name}")
async def delete_snapshot(snapshot_name: str, user: TokenPayload = Depends(require_admin)):
    success = await qc.delete_snapshot(snapshot_name)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete snapshot")
    log_audit(user.sub, "qdrant.snapshot.delete", {"name": snapshot_name})
    return {"ok": True, "deleted": snapshot_name}
