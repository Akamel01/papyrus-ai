"""
SME Research Assistant - Retry Policy

Per-stage retry with exponential backoff for pipeline operations.
"""

import logging
import time
from typing import Callable, TypeVar, Optional
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RetryExhausted(Exception):
    """Raised when all retries are exhausted. Takes a string to guarantee picklability."""
    def __init__(self, message: str):
        super().__init__(message)


class RetryPolicy:
    """
    Configurable retry policy with exponential backoff.
    
    Usage:
        policy = RetryPolicy(stage="embed", max_retries=3, base_delay=2.0, max_delay=30.0)
        result = policy.execute(embedder.embed, texts)
    """
    
    def __init__(
        self,
        stage: str,
        max_retries: int = 3,
        base_delay: float = 2.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
        retryable_exceptions: Optional[tuple] = None,
        exclude_exceptions: Optional[tuple] = None,
    ):
        """
        Args:
            stage: Human-readable stage name (for logging)
            max_retries: Maximum number of retry attempts
            base_delay: Initial delay between retries (seconds)
            max_delay: Maximum delay between retries (seconds)
            backoff_factor: Multiplier for exponential backoff
            retryable_exceptions: Tuple of exception types to retry on.
                                  If None, retries on all exceptions.
            exclude_exceptions: Tuple of exception types to NEVER retry on.
                                (Even if they are in retryable_exceptions)
        """
        self.stage = stage
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.retryable_exceptions = retryable_exceptions or (Exception,)
        self.exclude_exceptions = exclude_exceptions or ()
    
    def execute(self, fn: Callable, *args, **kwargs) -> T:
        """
        Execute a function with retry logic.
        
        Returns the function result on success.
        Raises RetryExhausted if all retries fail.
        """
        last_error = None
        
        for attempt in range(self.max_retries + 1):  # +1 for the initial attempt
            try:
                return fn(*args, **kwargs)
            except self.exclude_exceptions as e:
                # Fatal deterministic error — don't retry!
                logger.error(f"[RETRY-SKIP] Deterministic error in {self.stage}: {e}")
                err_msg = f"Retry exhausted for stage '{self.stage}' after {attempt + 1} attempts: {type(e).__name__} - {str(e)}"
                raise RetryExhausted(err_msg)
            except self.retryable_exceptions as e:
                last_error = e
                
                if attempt >= self.max_retries:
                    # All retries exhausted
                    logger.error(
                        f"[RETRY-EXHAUSTED] stage={self.stage}, "
                        f"attempts={attempt + 1}, error={e}"
                    )
                    err_msg = f"Retry exhausted for stage '{self.stage}' after {attempt + 1} attempts: {type(e).__name__} - {str(e)}"
                    raise RetryExhausted(err_msg)
                
                # Calculate delay with exponential backoff
                delay = min(
                    self.base_delay * (self.backoff_factor ** attempt),
                    self.max_delay
                )
                
                logger.warning(
                    f"[RETRY] stage={self.stage}, attempt={attempt + 1}/{self.max_retries}, "
                    f"delay={delay:.1f}s, error={e}"
                )
                time.sleep(delay)
        
        # Should never reach here, but just in case
        err_msg = f"Retry exhausted for stage '{self.stage}' after {self.max_retries} attempts: {type(last_error).__name__} - {str(last_error)}"
        raise RetryExhausted(err_msg)

# Pre-configured policies per stage (from performance upgrade plan Section 3.10)
CHUNK_RETRY = RetryPolicy(stage="chunk", max_retries=2, base_delay=1.0, max_delay=5.0)
EMBED_RETRY = RetryPolicy(stage="embed", max_retries=3, base_delay=2.0, max_delay=30.0)
STORE_RETRY = RetryPolicy(stage="store", max_retries=3, base_delay=2.0, max_delay=30.0)
