"""
SME Research Assistant - Security: Audit Logger

Logs all queries and actions for audit trail.
"""

import sqlite3
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from contextlib import contextmanager


@dataclass
class AuditEntry:
    """Audit log entry."""
    timestamp: str
    event_type: str  # "query", "feedback", "admin", "error"
    user_id: Optional[str]
    session_id: Optional[str]
    action: str
    details: Dict[str, Any]
    ip_address: Optional[str] = None
    duration_ms: Optional[float] = None


class AuditLogger:
    """
    Audit logger that stores entries in SQLite.
    """
    
    def __init__(self, db_path: str = "data/audit.db"):
        """Initialize audit logger with database path."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    user_id TEXT,
                    session_id TEXT,
                    action TEXT NOT NULL,
                    details TEXT,
                    ip_address TEXT,
                    duration_ms REAL,
                    created_at REAL NOT NULL
                )
            """)
            
            # Create indexes for common queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp 
                ON audit_log(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_user 
                ON audit_log(user_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_type 
                ON audit_log(event_type)
            """)
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """Get database connection with context manager."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def log(self, entry: AuditEntry) -> int:
        """
        Log an audit entry.
        
        Returns:
            ID of the inserted entry
        """
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO audit_log 
                (timestamp, event_type, user_id, session_id, action, 
                 details, ip_address, duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.timestamp,
                entry.event_type,
                entry.user_id,
                entry.session_id,
                entry.action,
                json.dumps(entry.details),
                entry.ip_address,
                entry.duration_ms,
                time.time()
            ))
            conn.commit()
            return cursor.lastrowid
    
    def log_query(self, query: str, user_id: Optional[str] = None,
                  session_id: Optional[str] = None,
                  response_preview: str = "",
                  duration_ms: float = 0,
                  sources_count: int = 0) -> int:
        """Convenience method to log a query."""
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            event_type="query",
            user_id=user_id,
            session_id=session_id,
            action="user_query",
            details={
                "query": query[:500],  # Truncate for storage
                "response_preview": response_preview[:200],
                "sources_count": sources_count
            },
            duration_ms=duration_ms
        )
        return self.log(entry)
    
    def log_feedback(self, query_id: int, rating: int, 
                     feedback_text: str = "",
                     user_id: Optional[str] = None) -> int:
        """Log user feedback on a response."""
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            event_type="feedback",
            user_id=user_id,
            session_id=None,
            action="user_feedback",
            details={
                "query_id": query_id,
                "rating": rating,
                "feedback": feedback_text[:500]
            }
        )
        return self.log(entry)
    
    def log_admin_action(self, action: str, details: Dict[str, Any],
                         user_id: Optional[str] = None) -> int:
        """Log admin action."""
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            event_type="admin",
            user_id=user_id,
            session_id=None,
            action=action,
            details=details
        )
        return self.log(entry)
    
    def log_error(self, error_type: str, error_message: str,
                  context: Dict[str, Any] = None,
                  user_id: Optional[str] = None) -> int:
        """Log an error."""
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            event_type="error",
            user_id=user_id,
            session_id=None,
            action=error_type,
            details={
                "message": error_message,
                "context": context or {}
            }
        )
        return self.log(entry)
    
    def get_entries(self, event_type: Optional[str] = None,
                    user_id: Optional[str] = None,
                    start_date: Optional[str] = None,
                    end_date: Optional[str] = None,
                    limit: int = 100) -> List[Dict]:
        """Query audit entries with filters."""
        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []
        
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        
        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
    
    def get_query_count(self, start_date: str, end_date: str) -> int:
        """Get count of queries in date range."""
        with self._get_connection() as conn:
            result = conn.execute("""
                SELECT COUNT(*) as count FROM audit_log 
                WHERE event_type = 'query' 
                AND timestamp >= ? AND timestamp <= ?
            """, (start_date, end_date)).fetchone()
            return result['count']


# Singleton instance
_audit_logger = None


def get_audit_logger(db_path: str = "data/audit.db") -> AuditLogger:
    """Get or create audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger(db_path)
    return _audit_logger
