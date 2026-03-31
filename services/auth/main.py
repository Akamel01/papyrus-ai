"""
SME Auth Service - Main FastAPI Application

Provides authentication, user management, and API key storage endpoints.
"""
import os
import re
import time
import logging
from collections import defaultdict
from datetime import datetime
from typing import List, Optional, Dict, Tuple

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session as DBSession

# Configure logging
logger = logging.getLogger(__name__)


# ─── Rate Limiting Configuration ───
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "100"))
LOGIN_LOCKOUT_ATTEMPTS = int(os.environ.get("LOGIN_LOCKOUT_ATTEMPTS", "10"))
LOGIN_LOCKOUT_MINUTES = int(os.environ.get("LOGIN_LOCKOUT_MINUTES", "15"))


class RateLimiter:
    """Simple in-memory rate limiter with per-IP and per-endpoint tracking."""

    def __init__(self):
        # {ip: [(timestamp, count)]}
        self.requests: Dict[str, List[float]] = defaultdict(list)
        # {ip: (failed_count, lockout_until)}
        self.failed_logins: Dict[str, Tuple[int, float]] = {}

    def is_rate_limited(self, ip: str, limit: int = RATE_LIMIT_PER_MINUTE) -> bool:
        """Check if IP is rate limited (general requests)."""
        now = time.time()
        window_start = now - 60  # 1 minute window

        # Clean old entries
        self.requests[ip] = [ts for ts in self.requests[ip] if ts > window_start]

        if len(self.requests[ip]) >= limit:
            return True

        self.requests[ip].append(now)
        return False

    def record_failed_login(self, ip: str) -> bool:
        """Record a failed login attempt. Returns True if now locked out."""
        now = time.time()

        # Check if currently locked out
        if ip in self.failed_logins:
            count, lockout_until = self.failed_logins[ip]
            if lockout_until > now:
                return True  # Still locked out

            # Lockout expired, check if we should reset
            if lockout_until < now:
                # Reset if lockout expired
                self.failed_logins[ip] = (1, 0)
                return False

        # Increment failed count
        current_count = self.failed_logins.get(ip, (0, 0))[0]
        new_count = current_count + 1

        if new_count >= LOGIN_LOCKOUT_ATTEMPTS:
            # Lock out for configured minutes
            lockout_until = now + (LOGIN_LOCKOUT_MINUTES * 60)
            self.failed_logins[ip] = (new_count, lockout_until)
            return True

        self.failed_logins[ip] = (new_count, 0)
        return False

    def is_login_locked(self, ip: str) -> Tuple[bool, int]:
        """Check if IP is locked out. Returns (is_locked, seconds_remaining)."""
        now = time.time()

        if ip not in self.failed_logins:
            return False, 0

        count, lockout_until = self.failed_logins[ip]
        if lockout_until > now:
            return True, int(lockout_until - now)

        return False, 0

    def clear_failed_logins(self, ip: str):
        """Clear failed login attempts for an IP (on successful login)."""
        if ip in self.failed_logins:
            del self.failed_logins[ip]


# Global rate limiter instance
rate_limiter = RateLimiter()

from models import (
    User, UserApiKey, UserPreferences, Session, AuditLog,
    get_engine, create_tables, get_session_factory
)
from auth import (
    hash_password, verify_password, create_token_pair,
    verify_token, TokenPair, TokenData, hash_refresh_token,
    verify_refresh_token_hash, ACCESS_TOKEN_EXPIRE_MINUTES
)
from crypto import encrypt_api_key, decrypt_api_key, mask_api_key
import json


# ─── Audit Logging Helper ───

def get_client_ip(request: Request) -> str:
    """Extract client IP address from request headers or client info."""
    # Check X-Forwarded-For header first (for reverse proxy scenarios)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, the first is the client
        return forwarded_for.split(",")[0].strip()
    # Fall back to direct client IP
    return request.client.host if request.client else "unknown"


def get_user_agent(request: Request) -> Optional[str]:
    """Extract user agent from request headers."""
    return request.headers.get("User-Agent")


def log_audit_event(
    db: DBSession,
    event_type: str,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[dict] = None
):
    """
    Log an audit event to the database.

    Args:
        db: Database session
        event_type: Type of event (login, logout, login_failed, register, password_change, api_key_add, api_key_delete, admin_action)
        user_id: ID of the user associated with the event (optional)
        ip_address: Client IP address
        user_agent: Client user agent string
        details: Additional context as a dictionary (will be JSON serialized)
    """
    audit_log = AuditLog(
        user_id=user_id,
        event_type=event_type,
        ip_address=ip_address,
        user_agent=user_agent,
        details=json.dumps(details) if details else None
    )
    db.add(audit_log)
    # Note: The caller is responsible for committing the transaction


# Initialize FastAPI app
app = FastAPI(
    title="SME Auth Service",
    description="Authentication and user management for SME Research Assistant",
    version="1.0.0"
)

# ─── CORS Configuration ───
# Read allowed origins from environment variable
# Default to common development origins if not set
CORS_ORIGINS_DEFAULT = ["http://localhost:8080", "http://localhost:8502", "http://localhost:3030"]
cors_origins_env = os.environ.get("CORS_ORIGINS", "")

if cors_origins_env:
    if cors_origins_env == "*":
        cors_origins = ["*"]
        logger.warning(
            "SECURITY WARNING: CORS is configured to allow all origins ('*'). "
            "This is not recommended for production. Set CORS_ORIGINS to specific domains."
        )
    else:
        # Parse comma-separated origins
        cors_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
else:
    cors_origins = CORS_ORIGINS_DEFAULT
    logger.info(f"CORS_ORIGINS not set, using defaults: {CORS_ORIGINS_DEFAULT}")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()

# Database setup
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/auth.db")
engine = get_engine(DATABASE_URL)
SessionLocal = get_session_factory(engine)


# Startup event
@app.on_event("startup")
async def startup():
    # Create tables if they don't exist
    create_tables(engine)

    # Create admin user if specified in environment
    admin_email = os.environ.get("ADMIN_EMAIL")
    admin_password = os.environ.get("ADMIN_PASSWORD")

    if admin_email and admin_password:
        db = SessionLocal()
        try:
            existing = db.query(User).filter(User.email == admin_email).first()
            if not existing:
                admin = User(
                    email=admin_email,
                    password_hash=hash_password(admin_password),
                    display_name="Admin",
                    role="admin"
                )
                db.add(admin)

                # Create default preferences
                prefs = UserPreferences(user_id=admin.id)
                db.add(prefs)

                db.commit()
                print(f"Created admin user: {admin_email}")
        finally:
            db.close()


# Dependency: Get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Dependency: Get current user from token
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: DBSession = Depends(get_db)
) -> User:
    token = credentials.credentials
    token_data = verify_token(token, expected_type="access")

    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == token_data.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    if user.is_active != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )

    return user


# ─── Request/Response Models ───

class RegisterRequest(BaseModel):
    email: EmailStr
    username: Optional[str] = None  # Optional username for login without email
    password: str
    display_name: Optional[str] = None

    @field_validator("username", mode="before")
    @classmethod
    def validate_username(cls, v):
        if v is None or v == "":
            return None
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        if len(v) > 30:
            raise ValueError("Username cannot exceed 30 characters")
        if "@" in v:
            raise ValueError("Username cannot contain '@'")
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("Username can only contain letters, numbers, underscores and hyphens")
        return v

    @field_validator("email")
    @classmethod
    def validate_email_not_reserved(cls, v):
        """Prevent registration with reserved usernames."""
        local_part = v.split("@")[0].lower()
        if local_part == "admin":
            raise ValueError("The username 'admin' is reserved and cannot be used for registration")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Password must contain at least one letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number")
        return v


class LoginRequest(BaseModel):
    """Login request - accepts email or username."""
    email: Optional[str] = None  # Can be email or username
    username: Optional[str] = None  # Alternative field name
    password: str

    @field_validator("email", "username", mode="before")
    @classmethod
    def strip_whitespace(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class InternalLoginRequest(BaseModel):
    """Login request for internal service-to-service auth (Dashboard -> Auth Service)."""
    username: str  # Can be email or username
    password: str


class InternalLoginResponse(BaseModel):
    """Response for internal login (includes dashboard_role)."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    email: str
    role: str  # Auth service role (user/admin)
    dashboard_role: Optional[str] = None  # Dashboard-specific role (admin/operator/viewer)


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: Optional[str]
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class ApiKeyRequest(BaseModel):
    key_name: str
    key_value: str

    @field_validator("key_name")
    @classmethod
    def validate_key_name(cls, v):
        allowed = ["openalex", "semantic_scholar", "ollama_cloud"]
        if v not in allowed:
            raise ValueError(f"key_name must be one of: {allowed}")
        return v


class ApiKeyResponse(BaseModel):
    id: str
    key_name: str
    masked_value: str
    created_at: datetime
    last_used: Optional[datetime]


class PreferencesRequest(BaseModel):
    preferred_model: Optional[str] = None
    research_depth: Optional[str] = None
    citation_style: Optional[str] = None
    ollama_mode: Optional[str] = None


class PreferencesResponse(BaseModel):
    preferred_model: str
    research_depth: str
    citation_style: str
    ollama_mode: str

    class Config:
        from_attributes = True


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters")
        return v


# ─── Auth Endpoints ───

@app.post("/api/auth/register", response_model=TokenPair)
async def register(request: RegisterRequest, req: Request, db: DBSession = Depends(get_db)):
    """Register a new user account."""
    # Rate limiting
    client_ip = get_client_ip(req)
    user_agent = get_user_agent(req)

    if rate_limiter.is_rate_limited(client_ip, limit=10):  # 10 registrations per minute max
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please wait a minute."
        )

    # Check if email already exists
    existing = db.query(User).filter(User.email == request.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Check if username already exists (if provided)
    if request.username:
        existing_username = db.query(User).filter(User.username == request.username).first()
        if existing_username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken"
            )

    # Create user
    user = User(
        email=request.email,
        username=request.username,
        password_hash=hash_password(request.password),
        display_name=request.display_name
    )
    db.add(user)
    db.flush()  # Flush to get user.id before creating preferences

    # Create default preferences
    prefs = UserPreferences(user_id=user.id)
    db.add(prefs)

    db.commit()
    db.refresh(user)

    # Create tokens
    tokens = create_token_pair(user.id, user.email, user.role)

    # Store session
    session = Session(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(tokens.refresh_token),
        expires_at=datetime.utcnow() + __import__("datetime").timedelta(days=7)
    )
    db.add(session)

    # Log audit event
    log_audit_event(
        db=db,
        event_type="register",
        user_id=user.id,
        ip_address=client_ip,
        user_agent=user_agent,
        details={"email": request.email}
    )

    db.commit()

    return tokens


@app.post("/api/auth/login", response_model=TokenPair)
async def login(request: LoginRequest, req: Request, db: DBSession = Depends(get_db)):
    """Login with email/username and password."""
    client_ip = get_client_ip(req)
    user_agent = get_user_agent(req)

    # Check if IP is locked out due to failed attempts
    is_locked, seconds_remaining = rate_limiter.is_login_locked(client_ip)
    if is_locked:
        minutes_remaining = (seconds_remaining // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Try again in {minutes_remaining} minute(s)."
        )

    # General rate limiting
    if rate_limiter.is_rate_limited(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please wait a minute."
        )

    # Get identifier from either email or username field
    identifier = request.email or request.username
    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please enter your username or email address"
        )

    # Try to find user by email first
    user = db.query(User).filter(User.email == identifier).first()

    # If not found, try by username column
    if not user:
        user = db.query(User).filter(User.username == identifier).first()

    # If still not found and identifier doesn't look like an email, try as dashboard username
    if not user and "@" not in identifier:
        dashboard_email = f"{identifier}@dashboard.local"
        user = db.query(User).filter(User.email == dashboard_email).first()

    if not user or not verify_password(request.password, user.password_hash):
        # Record failed login attempt
        # Log failed login attempt
        log_audit_event(
            db=db,
            event_type="login_failed",
            user_id=user.id if user else None,
            ip_address=client_ip,
            user_agent=user_agent,
            details={"identifier": identifier, "reason": "invalid_credentials"}
        )
        db.commit()

        if rate_limiter.record_failed_login(client_ip):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Account locked due to too many failed attempts. Try again in {LOGIN_LOCKOUT_MINUTES} minutes."
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username/email or password"
        )

    if user.is_active != "true":
        # Log disabled account login attempt
        log_audit_event(
            db=db,
            event_type="login_failed",
            user_id=user.id,
            ip_address=client_ip,
            user_agent=user_agent,
            details={"email": request.email, "reason": "account_disabled"}
        )
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )

    # Clear failed login attempts on successful login
    rate_limiter.clear_failed_logins(client_ip)

    # Update last login
    user.last_login = datetime.utcnow()

    # Create tokens
    tokens = create_token_pair(user.id, user.email, user.role)

    # Store session
    session = Session(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(tokens.refresh_token),
        expires_at=datetime.utcnow() + __import__("datetime").timedelta(days=7),
        ip_address=client_ip,
        user_agent=user_agent
    )
    db.add(session)

    # Log successful login
    log_audit_event(
        db=db,
        event_type="login",
        user_id=user.id,
        ip_address=client_ip,
        user_agent=user_agent,
        details={"email": user.email, "identifier_used": identifier}
    )

    db.commit()

    return tokens


@app.post("/api/auth/internal/login", response_model=InternalLoginResponse)
async def internal_login(request: InternalLoginRequest, db: DBSession = Depends(get_db)):
    """
    Internal login endpoint for service-to-service authentication.

    Used by Dashboard backend to authenticate against the unified auth service.
    No rate limiting applied (intended for internal network use only).

    Accepts username which can be either:
    - Email address (standard login)
    - Username field in User model
    - Username mapped to {username}@dashboard.local (for migrated dashboard users)
    """
    # Try to find user by email directly first
    user = db.query(User).filter(User.email == request.username).first()

    # If not found, try by username column
    if not user:
        user = db.query(User).filter(User.username == request.username).first()

    # If still not found, try treating username as a dashboard username (mapped to email)
    if not user:
        dashboard_email = f"{request.username}@dashboard.local"
        user = db.query(User).filter(User.email == dashboard_email).first()

    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    if user.is_active != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )

    # Update last login
    user.last_login = datetime.utcnow()

    # Create tokens
    tokens = create_token_pair(user.id, user.email, user.role)

    db.commit()

    return InternalLoginResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
        user_id=user.id,
        email=user.email,
        role=user.role,
        dashboard_role=user.dashboard_role
    )


@app.post("/api/auth/refresh", response_model=TokenPair)
async def refresh_token(request: RefreshRequest, req: Request, db: DBSession = Depends(get_db)):
    """Refresh access token using refresh token."""
    # Rate limiting
    client_ip = req.client.host if req.client else "unknown"
    if rate_limiter.is_rate_limited(client_ip, limit=30):  # 30 refreshes per minute max
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many refresh attempts. Please wait."
        )

    token_data = verify_token(request.refresh_token, expected_type="refresh")

    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    user = db.query(User).filter(User.id == token_data.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    # Create new token pair
    tokens = create_token_pair(user.id, user.email, user.role)

    # Update session with new refresh token hash
    session = db.query(Session).filter(Session.user_id == user.id).first()
    if session:
        session.refresh_token_hash = hash_refresh_token(tokens.refresh_token)
        session.expires_at = datetime.utcnow() + __import__("datetime").timedelta(days=7)
        db.commit()

    return tokens


@app.post("/api/auth/logout")
async def logout(
    req: Request,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db)
):
    """Logout and invalidate session."""
    client_ip = get_client_ip(req)
    user_agent = get_user_agent(req)

    # Delete all sessions for this user
    db.query(Session).filter(Session.user_id == current_user.id).delete()

    # Log logout event
    log_audit_event(
        db=db,
        event_type="logout",
        user_id=current_user.id,
        ip_address=client_ip,
        user_agent=user_agent,
        details={"email": current_user.email}
    )

    db.commit()

    return {"message": "Logged out successfully"}


# ─── User Endpoints ───

@app.get("/api/auth/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information."""
    return current_user


@app.put("/api/auth/me")
async def update_user(
    display_name: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db)
):
    """Update user profile."""
    if display_name is not None:
        current_user.display_name = display_name
        db.commit()

    return {"message": "Profile updated"}


@app.post("/api/auth/me/password")
async def change_password(
    request: PasswordChangeRequest,
    req: Request,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db)
):
    """Change user password."""
    client_ip = get_client_ip(req)
    user_agent = get_user_agent(req)

    if not verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    current_user.password_hash = hash_password(request.new_password)

    # Log password change event
    log_audit_event(
        db=db,
        event_type="password_change",
        user_id=current_user.id,
        ip_address=client_ip,
        user_agent=user_agent,
        details={"email": current_user.email}
    )

    db.commit()

    return {"message": "Password changed successfully"}


# ─── API Key Endpoints ───

@app.get("/api/auth/me/keys", response_model=List[ApiKeyResponse])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db)
):
    """List all API keys for current user (values are masked)."""
    keys = db.query(UserApiKey).filter(UserApiKey.user_id == current_user.id).all()

    result = []
    for key in keys:
        # Decrypt to get masked version
        try:
            decrypted = decrypt_api_key(current_user.id, key.encrypted_value)
            masked = mask_api_key(decrypted)
        except Exception:
            masked = "****"

        result.append(ApiKeyResponse(
            id=key.id,
            key_name=key.key_name,
            masked_value=masked,
            created_at=key.created_at,
            last_used=key.last_used
        ))

    return result


@app.put("/api/auth/me/keys")
async def upsert_api_key(
    request: ApiKeyRequest,
    req: Request,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db)
):
    """Add or update an API key."""
    client_ip = get_client_ip(req)
    user_agent = get_user_agent(req)

    # Encrypt the key
    encrypted = encrypt_api_key(current_user.id, request.key_value)

    # Check if key exists
    existing = db.query(UserApiKey).filter(
        UserApiKey.user_id == current_user.id,
        UserApiKey.key_name == request.key_name
    ).first()

    if existing:
        existing.encrypted_value = encrypted
        existing.created_at = datetime.utcnow()
    else:
        new_key = UserApiKey(
            user_id=current_user.id,
            key_name=request.key_name,
            encrypted_value=encrypted
        )
        db.add(new_key)

    # Log API key add event
    log_audit_event(
        db=db,
        event_type="api_key_add",
        user_id=current_user.id,
        ip_address=client_ip,
        user_agent=user_agent,
        details={"key_name": request.key_name, "action": "update" if existing else "create"}
    )

    db.commit()

    return {"message": f"API key '{request.key_name}' saved successfully"}


@app.delete("/api/auth/me/keys/{key_name}")
async def delete_api_key(
    key_name: str,
    req: Request,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db)
):
    """Delete an API key."""
    client_ip = get_client_ip(req)
    user_agent = get_user_agent(req)

    deleted = db.query(UserApiKey).filter(
        UserApiKey.user_id == current_user.id,
        UserApiKey.key_name == key_name
    ).delete()

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key '{key_name}' not found"
        )

    # Log API key delete event
    log_audit_event(
        db=db,
        event_type="api_key_delete",
        user_id=current_user.id,
        ip_address=client_ip,
        user_agent=user_agent,
        details={"key_name": key_name}
    )

    db.commit()

    return {"message": f"API key '{key_name}' deleted"}


# ─── Preferences Endpoints ───

@app.get("/api/auth/me/preferences", response_model=PreferencesResponse)
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db)
):
    """Get user preferences."""
    prefs = db.query(UserPreferences).filter(
        UserPreferences.user_id == current_user.id
    ).first()

    if not prefs:
        # Create default preferences
        prefs = UserPreferences(user_id=current_user.id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)

    return prefs


@app.put("/api/auth/me/preferences", response_model=PreferencesResponse)
async def update_preferences(
    request: PreferencesRequest,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db)
):
    """Update user preferences."""
    prefs = db.query(UserPreferences).filter(
        UserPreferences.user_id == current_user.id
    ).first()

    if not prefs:
        prefs = UserPreferences(user_id=current_user.id)
        db.add(prefs)

    if request.preferred_model is not None:
        prefs.preferred_model = request.preferred_model
    if request.research_depth is not None:
        prefs.research_depth = request.research_depth
    if request.citation_style is not None:
        prefs.citation_style = request.citation_style
    if request.ollama_mode is not None:
        prefs.ollama_mode = request.ollama_mode

    prefs.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(prefs)

    return prefs


# ─── Internal Endpoints (for other services) ───

@app.get("/api/auth/internal/user/{user_id}/api-key/{key_name}")
async def get_api_key_internal(
    user_id: str,
    key_name: str,
    db: DBSession = Depends(get_db)
):
    """
    Get decrypted API key for a user (internal use only).

    This endpoint should be protected by internal network / service mesh.
    """
    key = db.query(UserApiKey).filter(
        UserApiKey.user_id == user_id,
        UserApiKey.key_name == key_name
    ).first()

    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key '{key_name}' not found for user"
        )

    # Update last used
    key.last_used = datetime.utcnow()
    db.commit()

    try:
        decrypted = decrypt_api_key(user_id, key.encrypted_value)
        return {"key_value": decrypted}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to decrypt API key: {e}"
        )


@app.get("/api/auth/internal/validate")
async def validate_token_internal(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Validate a token and return user info (internal use only).

    Used by other services to validate incoming requests.
    """
    token = credentials.credentials
    token_data = verify_token(token, expected_type="access")

    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    return {
        "user_id": token_data.user_id,
        "email": token_data.email,
        "role": token_data.role
    }


# ─── Admin Endpoints ───

class AuditLogResponse(BaseModel):
    id: str
    timestamp: datetime
    user_id: Optional[str]
    event_type: str
    ip_address: Optional[str]
    user_agent: Optional[str]
    details: Optional[str]

    class Config:
        from_attributes = True


@app.get("/api/auth/admin/audit-logs", response_model=List[AuditLogResponse])
async def get_audit_logs(
    limit: int = 100,
    offset: int = 0,
    event_type: Optional[str] = None,
    user_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db)
):
    """
    Get audit log entries (admin only).

    Args:
        limit: Maximum number of entries to return (default 100)
        offset: Number of entries to skip (default 0)
        event_type: Filter by event type (optional)
        user_id: Filter by user ID (optional)
    """
    # Check admin role
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    # Build query
    query = db.query(AuditLog)

    # Apply filters
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)

    # Order by timestamp descending (most recent first)
    query = query.order_by(AuditLog.timestamp.desc())

    # Apply pagination
    audit_logs = query.offset(offset).limit(limit).all()

    return audit_logs


# ─── Health Check ───

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "auth"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
