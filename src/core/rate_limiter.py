"""
Rate limiting utilities with exponential backoff.
Handles 429 (Too Many Requests) errors gracefully.
"""

import time
import random
import logging
from functools import wraps
from typing import Callable, Any, Optional

import requests
from requests.exceptions import HTTPError

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """Raised when max retries exceeded for rate-limited requests."""
    pass


class RateLimiter:
    """
    Rate limiter with exponential backoff for API requests.
    
    Usage:
        limiter = RateLimiter(requests_per_second=1.0)
        response = limiter.request_with_backoff(requests.get, url)
    """
    
    def __init__(
        self, 
        requests_per_second: float = 1.0, 
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0
    ):
        """
        Initialize rate limiter.
        
        Args:
            requests_per_second: Max requests per second (e.g., 1.0 = 1 req/sec)
            max_retries: Max retry attempts on 429 errors
            base_delay: Initial backoff delay in seconds
            max_delay: Maximum backoff delay in seconds
        """
        self.min_interval = 1.0 / requests_per_second
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.last_request = 0.0
    
    def wait(self):
        """Wait to respect rate limit between requests."""
        elapsed = time.time() - self.last_request
        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            time.sleep(sleep_time)
        self.last_request = time.time()
    
    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter."""
        delay = self.base_delay * (2 ** attempt)
        delay = min(delay, self.max_delay)
        # Add jitter (±25%) to prevent thundering herd
        jitter = delay * 0.25 * (random.random() * 2 - 1)
        return delay + jitter
    
    def request_with_backoff(
        self, 
        func: Callable, 
        *args, 
        **kwargs
    ) -> Any:
        """
        Execute request function with rate limiting and exponential backoff.
        
        Args:
            func: Request function to call (e.g., requests.get)
            *args, **kwargs: Arguments to pass to func
            
        Returns:
            Response from func
            
        Raises:
            RateLimitExceeded: If max retries exceeded
            HTTPError: For non-429 HTTP errors
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                self.wait()
                response = func(*args, **kwargs)
                
                # Check for rate limit response
                if hasattr(response, 'status_code') and response.status_code == 429:
                    raise HTTPError(response=response)
                
                # Raise for other HTTP errors
                if hasattr(response, 'raise_for_status'):
                    response.raise_for_status()
                    
                return response
                
            except HTTPError as e:
                status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
                
                if status_code == 429:
                    wait_time = self._calculate_backoff(attempt)
                    logger.warning(
                        f"Rate limited (429). Attempt {attempt + 1}/{self.max_retries}. "
                        f"Waiting {wait_time:.1f}s before retry..."
                    )
                    time.sleep(wait_time)
                    last_exception = e
                else:
                    # Non-429 error, re-raise immediately
                    raise
        
        # Max retries exceeded
        logger.error(f"Rate limit exceeded after {self.max_retries} retries")
        raise RateLimitExceeded(
            f"Max retries ({self.max_retries}) exceeded for rate-limited request"
        ) from last_exception


def with_rate_limit(limiter: RateLimiter):
    """
    Decorator to apply rate limiting to a function.
    
    Usage:
        limiter = RateLimiter(requests_per_second=1.0)
        
        @with_rate_limit(limiter)
        def fetch_data(url):
            return requests.get(url)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            return limiter.request_with_backoff(
                lambda: func(*args, **kwargs)
            )
        return wrapper
    return decorator


# Pre-configured limiters for common APIs
SEMANTIC_SCHOLAR_LIMITER = RateLimiter(
    requests_per_second=1.0,  # 1 RPS with API key
    max_retries=5,
    base_delay=2.0
)

OPENALEX_LIMITER = RateLimiter(
    requests_per_second=10.0,  # 10 RPS with API key
    max_retries=3,
    base_delay=1.0
)

UNPAYWALL_LIMITER = RateLimiter(
    requests_per_second=10.0,  # ~100k/day = ~1.16/sec, use 10 to be safe
    max_retries=3,
    base_delay=1.0
)
