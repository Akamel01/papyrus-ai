"""Auth routes: login, refresh, me, create-user."""
from fastapi import APIRouter, HTTPException, Depends
from auth import (
    LoginRequest, TokenResponse, authenticate_user,
    create_access_token, create_refresh_token, decode_token,
    get_current_user, require_admin, create_user, TokenPayload,
)

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenResponse(
        access_token=create_access_token(user["username"], user["role"]),
        refresh_token=create_refresh_token(user["username"], user["role"]),
        role=user["role"],
        expires_in=900,
    )


@router.post("/refresh")
async def refresh(refresh_token: str):
    payload = decode_token(refresh_token)
    return {
        "access_token": create_access_token(payload.sub, payload.role),
        "expires_in": 900,
    }


@router.get("/me")
async def me(user: TokenPayload = Depends(get_current_user)):
    return {"user_id": user.sub, "role": user.role, "username": user.sub}


@router.post("/create-user")
async def create_user_endpoint(username: str, password: str, role: str,
                               _admin: TokenPayload = Depends(require_admin)):
    try:
        create_user(username, password, role)
        return {"ok": True, "username": username, "role": role}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
