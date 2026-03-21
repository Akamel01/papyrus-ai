"""Config routes: read, validate, save, versions, revert."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from auth import require_viewer, require_admin, TokenPayload
import config_manager
from audit_logger import log_audit

router = APIRouter()


class ValidateRequest(BaseModel):
    yaml: str


class SaveRequest(BaseModel):
    yaml: str
    etag: str


class RevertRequest(BaseModel):
    version_path: str


@router.get("")
async def get_config(_user: TokenPayload = Depends(require_viewer)):
    try:
        return config_manager.read_config()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")


@router.post("/validate")
async def validate_config(req: ValidateRequest, _user: TokenPayload = Depends(require_viewer)):
    return config_manager.validate_config(req.yaml)


@router.post("/save")
async def save_config(req: SaveRequest, user: TokenPayload = Depends(require_admin)):
    try:
        result = config_manager.save_config(req.yaml, req.etag, user.sub)
        return result
    except ValueError as e:
        if "modified by another" in str(e).lower():
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/versions")
async def list_versions(_user: TokenPayload = Depends(require_admin)):
    return config_manager.list_versions()


@router.post("/revert")
async def revert_config(req: RevertRequest, user: TokenPayload = Depends(require_admin)):
    try:
        result = config_manager.revert_config(req.version_path, user.sub)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
