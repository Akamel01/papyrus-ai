"""
SME Research Assistant - Security: Authentication

Simple password-based authentication for Streamlit UI.
"""

import hashlib
import secrets
import time
from typing import Optional, Dict
from dataclasses import dataclass, field


@dataclass
class Session:
    """User session data."""
    user_id: str
    created_at: float
    last_active: float
    metadata: Dict = field(default_factory=dict)


class AuthManager:
    """
    Simple authentication manager.
    
    For production, consider using proper auth like OAuth2.
    """
    
    def __init__(self, session_timeout: int = 3600):
        """
        Initialize auth manager.
        
        Args:
            session_timeout: Session timeout in seconds (default 1 hour)
        """
        self.session_timeout = session_timeout
        self._sessions: Dict[str, Session] = {}
        self._users: Dict[str, str] = {}  # username -> password_hash
        
        # Add default admin user (change in production!)
        self.add_user("admin", "sme_research_2024")
    
    def add_user(self, username: str, password: str) -> None:
        """Add a user with password."""
        self._users[username] = self._hash_password(password)
    
    def _hash_password(self, password: str) -> str:
        """Hash password with salt."""
        salt = "sme_research_salt_"  # In production, use unique salt per user
        return hashlib.sha256((salt + password).encode()).hexdigest()
    
    def authenticate(self, username: str, password: str) -> Optional[str]:
        """
        Authenticate user and create session.
        
        Args:
            username: Username
            password: Plain text password
            
        Returns:
            Session token if successful, None otherwise
        """
        if username not in self._users:
            return None
        
        if self._users[username] != self._hash_password(password):
            return None
        
        # Create session
        token = secrets.token_urlsafe(32)
        now = time.time()
        self._sessions[token] = Session(
            user_id=username,
            created_at=now,
            last_active=now
        )
        
        return token
    
    def validate_session(self, token: str) -> Optional[Session]:
        """
        Validate session token.
        
        Args:
            token: Session token
            
        Returns:
            Session if valid, None otherwise
        """
        if token not in self._sessions:
            return None
        
        session = self._sessions[token]
        now = time.time()
        
        # Check timeout
        if now - session.last_active > self.session_timeout:
            del self._sessions[token]
            return None
        
        # Update last active
        session.last_active = now
        return session
    
    def logout(self, token: str) -> None:
        """Invalidate session."""
        if token in self._sessions:
            del self._sessions[token]
    
    def cleanup_expired(self) -> int:
        """Remove expired sessions. Returns count of removed sessions."""
        now = time.time()
        expired = [
            token for token, session in self._sessions.items()
            if now - session.last_active > self.session_timeout
        ]
        for token in expired:
            del self._sessions[token]
        return len(expired)


# Singleton instance
_auth_manager = None


def get_auth_manager(session_timeout: int = 3600) -> AuthManager:
    """Get or create auth manager instance."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager(session_timeout)
    return _auth_manager
