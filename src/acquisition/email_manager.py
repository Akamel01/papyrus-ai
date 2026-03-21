"""
SME Research Assistant - Email Manager

Manages email rotation for API rate limit handling.
Implements fallback strategy when rate limited.
"""

import logging
import threading
from typing import List, Optional
from dataclasses import dataclass
import time

logger = logging.getLogger(__name__)


@dataclass
class EmailStatus:
    """Tracks status of an email address."""
    email: str
    rate_limited_until: float = 0.0
    request_count: int = 0
    error_count: int = 0


class EmailRotator:
    """
    Manages email rotation for API requests.
    
    Automatically rotates to next available email when:
    - Current email hits rate limit (429 error)
    - Current email exceeds error threshold
    
    Features:
    - Thread-safe rotation
    - Automatic cooldown tracking
    - Fallback to next available email
    """
    
    DEFAULT_COOLDOWN_SECONDS = 300  # 5 minutes
    
    def __init__(
        self,
        emails: List[str],
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    ):
        """
        Initialize email rotator.
        
        Args:
            emails: List of email addresses to rotate through
            cooldown_seconds: Time to wait before reusing rate-limited email
        """
        if not emails:
            raise ValueError("At least one email is required")
        
        self.emails = [EmailStatus(email=e) for e in emails]
        self.cooldown_seconds = cooldown_seconds
        self.current_index = 0
        self._lock = threading.Lock()
        
        logger.info(f"EmailRotator initialized with {len(emails)} emails")
    
    def get_current_email(self) -> str:
        """Get the current active email address."""
        with self._lock:
            return self.emails[self.current_index].email
    
    def get_available_email(self) -> Optional[str]:
        """
        Get first available (non-rate-limited) email.
        
        Returns:
            Available email address or None if all are rate limited
        """
        current_time = time.time()
        
        with self._lock:
            # Check current email first
            current = self.emails[self.current_index]
            if current.rate_limited_until <= current_time:
                return current.email
            
            # Find next available
            for i in range(len(self.emails)):
                idx = (self.current_index + i) % len(self.emails)
                email_status = self.emails[idx]
                
                if email_status.rate_limited_until <= current_time:
                    self.current_index = idx
                    logger.info(f"Rotated to email: {email_status.email}")
                    return email_status.email
            
            # All rate limited - return time until first available
            soonest = min(e.rate_limited_until for e in self.emails)
            wait_time = soonest - current_time
            logger.warning(f"All emails rate limited. Next available in {wait_time:.1f}s")
            return None
    
    def mark_rate_limited(self, email: Optional[str] = None):
        """
        Mark an email as rate limited.
        
        Args:
            email: Email to mark (uses current if None)
        """
        with self._lock:
            if email is None:
                email_status = self.emails[self.current_index]
            else:
                email_status = next(
                    (e for e in self.emails if e.email == email),
                    None
                )
            
            if email_status:
                email_status.rate_limited_until = time.time() + self.cooldown_seconds
                email_status.error_count += 1
                logger.warning(
                    f"Email {email_status.email} rate limited. "
                    f"Cooldown: {self.cooldown_seconds}s"
                )
                
                # Auto-rotate to next
                self._rotate_to_next()
    
    def mark_success(self, email: Optional[str] = None):
        """Record successful request for email."""
        with self._lock:
            if email is None:
                email_status = self.emails[self.current_index]
            else:
                email_status = next(
                    (e for e in self.emails if e.email == email),
                    None
                )
            
            if email_status:
                email_status.request_count += 1
    
    def _rotate_to_next(self):
        """Internal: Rotate to next email (no lock)."""
        original_index = self.current_index
        current_time = time.time()
        
        for i in range(1, len(self.emails)):
            idx = (original_index + i) % len(self.emails)
            if self.emails[idx].rate_limited_until <= current_time:
                self.current_index = idx
                logger.info(f"Auto-rotated to: {self.emails[idx].email}")
                return
        
        # All rate limited, stay on current (it will fail gracefully)
        logger.warning("All emails rate limited, no rotation possible")
    
    def wait_for_available(self, timeout: float = 600) -> Optional[str]:
        """
        Wait until an email becomes available.
        
        Args:
            timeout: Maximum seconds to wait
            
        Returns:
            Available email or None if timeout
        """
        start = time.time()
        
        while time.time() - start < timeout:
            email = self.get_available_email()
            if email:
                return email
            
            # Calculate shortest wait
            current_time = time.time()
            wait_times = [
                e.rate_limited_until - current_time 
                for e in self.emails 
                if e.rate_limited_until > current_time
            ]
            
            if not wait_times:
                return self.get_available_email()
            
            wait = min(wait_times) + 1  # Add 1 second buffer
            if wait > 0:
                logger.info(f"Waiting {wait:.1f}s for email cooldown...")
                time.sleep(min(wait, timeout - (time.time() - start)))
        
        logger.error(f"Timeout waiting for available email ({timeout}s)")
        return None
    
    def get_stats(self) -> dict:
        """Get statistics for all emails."""
        with self._lock:
            return {
                "emails": [
                    {
                        "email": e.email,
                        "requests": e.request_count,
                        "errors": e.error_count,
                        "rate_limited": e.rate_limited_until > time.time()
                    }
                    for e in self.emails
                ],
                "current_index": self.current_index
            }
