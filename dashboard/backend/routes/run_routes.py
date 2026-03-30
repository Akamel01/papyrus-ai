"""Run control routes: status, precheck, start, stop."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from auth import require_viewer, require_admin, TokenPayload
from command_runner import tracker

router = APIRouter()


class StartRequest(BaseModel):
    mode: str  # "stream" | "embed-only" | "test"


class StopRequest(BaseModel):
    force: bool = False


@router.get("/status")
async def get_status(_user: TokenPayload = Depends(require_viewer)):
    return tracker.get_status()


@router.get("/precheck")
async def precheck(_user: TokenPayload = Depends(require_admin)):
    """
    Run pre-flight checks before starting the pipeline.
    Returns detailed check results that can be used by the frontend to:
    - Show user what's ready
    - Highlight what needs fixing
    - Enable/disable the Start button
    """
    checks = tracker.run_precheck()

    # Determine overall status
    all_pass = all(c["status"] == "pass" for c in checks)
    any_fail = any(c["status"] == "fail" for c in checks)

    return {
        "checks": checks,
        "ready": all_pass,
        "can_start": not any_fail,  # Can start if no failures (warnings are ok)
        "summary": "✅ Ready to start" if all_pass else "⚠️ Some checks need attention" if any_fail else "Ready"
    }


@router.post("/start")
async def start_pipeline(req: StartRequest, user: TokenPayload = Depends(require_admin)):
    try:
        return tracker.start(req.mode, user.sub)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        if "already running" in str(e).lower():
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_pipeline(req: StopRequest, user: TokenPayload = Depends(require_admin)):
    try:
        return tracker.stop(req.force, user.sub)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
