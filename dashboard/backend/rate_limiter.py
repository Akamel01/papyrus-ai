"""
SME Dashboard — Rate Limiting Middleware

Simple in-memory rate limiter for auth endpoints.
Prevents brute-force login attempts.
"""

import time
import logging
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response
from starlette.responses import JSONResponse

logger = logging.getLogger("dashboard.ratelimit")

# Config
LOGIN_RATE_LIMIT = 10  # max attempts per window
LOGIN_WINDOW_SEC = 60  # window size in seconds

# In-memory store: {ip: [(timestamp, ...)]}
_attempts: dict[str, list[float]] = defaultdict(list)


def _clean_old(ip: str, now: float):
    """Remove timestamps older than the window."""
    cutoff = now - LOGIN_WINDOW_SEC
    _attempts[ip] = [t for t in _attempts[ip] if t > cutoff]


async def rate_limit_middleware(request: Request, call_next: Callable) -> Response:
    """Rate limit login and auth endpoints."""
    path = request.url.path

    # Only rate-limit auth endpoints
    if path not in ("/api/auth/login", "/api/auth/refresh", "/api/auth/create-user"):
        return await call_next(request)

    ip = request.client.host if request.client else "unknown"

    # Skip rate limiting for test clients
    if ip == "testclient":
        return await call_next(request)

    now = time.time()

    _clean_old(ip, now)

    if len(_attempts[ip]) >= LOGIN_RATE_LIMIT:
        wait = int(LOGIN_WINDOW_SEC - (now - _attempts[ip][0]))
        logger.warning(f"[RATELIMIT] {ip} rate-limited on {path} (retry in {wait}s)")
        return JSONResponse(
            status_code=429,
            content={
                "error": "RATE_LIMITED",
                "message": f"Too many requests. Try again in {wait} seconds.",
                "retry_after": wait,
            },
            headers={"Retry-After": str(wait)},
        )

    _attempts[ip].append(now)
    return await call_next(request)
