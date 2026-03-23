"""
SME Dashboard — JWT Authentication & Role-Based Access Control

Roles: admin, operator, viewer
Auth: JWT Bearer tokens (15min access, 7d refresh)

Authentication Backend:
- If USE_UNIFIED_AUTH=true: Proxy to Auth Service (services/auth)
- If USE_UNIFIED_AUTH=false: Use local JSON file (data/dashboard_users.json)
"""

import json
import os
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

logger = logging.getLogger("dashboard.auth")

# --- Config ---
JWT_SECRET = os.getenv("JWT_SECRET", "CHANGE_ME_IN_PRODUCTION")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MIN = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7
USERS_FILE = os.getenv("USERS_FILE", "/data/dashboard_users.json")

# Unified Auth Service configuration
USE_UNIFIED_AUTH = os.getenv("USE_UNIFIED_AUTH", "true").lower() == "true"
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth:8000")

security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ROLE_HIERARCHY = {"admin": 3, "operator": 2, "viewer": 1}


# --- Models ---
class User(BaseModel):
    username: str
    role: str  # admin | operator | viewer
    hashed_password: str


class TokenPayload(BaseModel):
    sub: str  # username
    role: str
    exp: float


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    role: str
    expires_in: int


# --- User store ---
def _load_users() -> dict[str, dict]:
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r") as f:
        return json.load(f)


def _save_users(users: dict):
    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)


def create_user(username: str, password: str, role: str = "viewer"):
    """Create a new user. Called from CLI or admin endpoint."""
    if role not in ROLE_HIERARCHY:
        raise ValueError(f"Invalid role: {role}. Must be one of {list(ROLE_HIERARCHY)}")
    users = _load_users()
    if username in users:
        raise ValueError(f"User '{username}' already exists")
    users[username] = {
        "username": username,
        "role": role,
        "hashed_password": pwd_context.hash(password),
    }
    _save_users(users)
    logger.info(f"[AUTH] User created: {username} (role={role})")


# --- Token creation ---
def _create_token(username: str, role: str, expires_delta: timedelta) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {"sub": username, "role": role, "exp": expire.timestamp()}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_access_token(username: str, role: str) -> str:
    return _create_token(username, role, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MIN))


def create_refresh_token(username: str, role: str) -> str:
    return _create_token(username, role, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))


# --- Authentication ---
def authenticate_user(username: str, password: str) -> Optional[dict]:
    """
    Authenticate a user by username and password.

    If USE_UNIFIED_AUTH is enabled, calls the Auth Service.
    Otherwise, uses the local JSON file.
    """
    if USE_UNIFIED_AUTH:
        return _authenticate_via_auth_service(username, password)
    else:
        return _authenticate_via_json(username, password)


def _authenticate_via_json(username: str, password: str) -> Optional[dict]:
    """Authenticate using local JSON file (legacy mode)."""
    users = _load_users()
    user = users.get(username)
    if not user:
        return None
    if not pwd_context.verify(password, user["hashed_password"]):
        return None
    return user


def _authenticate_via_auth_service(username: str, password: str) -> Optional[dict]:
    """
    Authenticate via the unified Auth Service.

    Returns user dict with tokens if successful, None otherwise.
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{AUTH_SERVICE_URL}/api/auth/internal/login",
                json={"username": username, "password": password}
            )

            if response.status_code == 200:
                data = response.json()
                # Map Auth Service response to Dashboard format
                # Determine dashboard role: use dashboard_role if set, otherwise map from auth role
                dashboard_role = data.get("dashboard_role")
                if not dashboard_role:
                    # Map auth service role to dashboard role
                    auth_role = data.get("role", "user")
                    dashboard_role = "admin" if auth_role == "admin" else "viewer"

                return {
                    "username": username,
                    "role": dashboard_role,
                    "hashed_password": "",  # Not needed when using Auth Service
                    "user_id": data.get("user_id"),
                    "email": data.get("email"),
                    # Include tokens from Auth Service for potential passthrough
                    "_auth_service_tokens": {
                        "access_token": data.get("access_token"),
                        "refresh_token": data.get("refresh_token"),
                        "expires_in": data.get("expires_in"),
                    }
                }
            elif response.status_code == 401:
                logger.debug(f"[AUTH] Auth Service rejected credentials for {username}")
                return None
            elif response.status_code == 403:
                logger.warning(f"[AUTH] Account disabled for {username}")
                return None
            else:
                logger.error(f"[AUTH] Auth Service error: {response.status_code} - {response.text}")
                return None

    except httpx.RequestError as e:
        logger.error(f"[AUTH] Failed to reach Auth Service: {e}")
        # Fallback to JSON auth if Auth Service is unavailable
        logger.warning("[AUTH] Falling back to JSON auth due to Auth Service unavailability")
        return _authenticate_via_json(username, password)
    except Exception as e:
        logger.error(f"[AUTH] Unexpected error during Auth Service auth: {e}")
        return None


def decode_token(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return TokenPayload(**payload)
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


# --- Dependencies ---
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenPayload:
    return decode_token(credentials.credentials)


def require_role(min_role: str):
    """Dependency factory: require minimum role level."""
    min_level = ROLE_HIERARCHY.get(min_role, 0)

    async def _check(user: TokenPayload = Depends(get_current_user)):
        user_level = ROLE_HIERARCHY.get(user.role, 0)
        if user_level < min_level:
            raise HTTPException(
                status_code=403,
                detail=f"Requires {min_role} role (you have {user.role})",
            )
        return user

    return _check


# Convenience aliases
require_viewer = require_role("viewer")
require_operator = require_role("operator")
require_admin = require_role("admin")
