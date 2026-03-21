"""
SME Auth Service - Authentication Module

Handles JWT token generation, validation, and password hashing.
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel


# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenData(BaseModel):
    """Data extracted from a JWT token."""
    user_id: str
    email: str
    role: str
    token_type: str  # "access" or "refresh"


class TokenPair(BaseModel):
    """Access and refresh token pair."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expires


# Configuration
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7
ALGORITHM = "HS256"


def get_jwt_secret() -> str:
    """Get JWT secret from environment."""
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise ValueError(
            "JWT_SECRET environment variable is required. "
            "Generate with: openssl rand -base64 32"
        )
    return secret


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Hashed password string
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.

    Args:
        plain_password: Plain text password to verify
        hashed_password: Stored hash

    Returns:
        True if password matches
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.

    Args:
        user_id: User's unique identifier
        email: User's email
        role: User's role (user, admin)
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT string
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    expire = datetime.utcnow() + expires_delta
    to_encode = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(to_encode, get_jwt_secret(), algorithm=ALGORITHM)


def create_refresh_token(
    user_id: str,
    email: str,
    role: str,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT refresh token.

    Args:
        user_id: User's unique identifier
        email: User's email
        role: User's role
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT string
    """
    if expires_delta is None:
        expires_delta = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    expire = datetime.utcnow() + expires_delta
    to_encode = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(to_encode, get_jwt_secret(), algorithm=ALGORITHM)


def create_token_pair(user_id: str, email: str, role: str) -> TokenPair:
    """
    Create both access and refresh tokens.

    Args:
        user_id: User's unique identifier
        email: User's email
        role: User's role

    Returns:
        TokenPair with both tokens
    """
    access_token = create_access_token(user_id, email, role)
    refresh_token = create_refresh_token(user_id, email, role)

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


def verify_token(token: str, expected_type: str = "access") -> Optional[TokenData]:
    """
    Verify and decode a JWT token.

    Args:
        token: JWT string to verify
        expected_type: Expected token type ("access" or "refresh")

    Returns:
        TokenData if valid, None if invalid
    """
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[ALGORITHM])

        token_type = payload.get("type")
        if token_type != expected_type:
            return None

        user_id = payload.get("sub")
        email = payload.get("email")
        role = payload.get("role")

        if not all([user_id, email, role]):
            return None

        return TokenData(
            user_id=user_id,
            email=email,
            role=role,
            token_type=token_type
        )

    except JWTError:
        return None


def hash_refresh_token(token: str) -> str:
    """
    Hash a refresh token for storage.

    We don't store raw refresh tokens, only their hashes.
    """
    return pwd_context.hash(token)


def verify_refresh_token_hash(token: str, hashed_token: str) -> bool:
    """Verify a refresh token against its stored hash."""
    return pwd_context.verify(token, hashed_token)
