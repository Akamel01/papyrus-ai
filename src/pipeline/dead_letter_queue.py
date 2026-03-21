"""
SME Research Assistant - Dead Letter Queue

SQLite-backed dead-letter queue for pipeline items that fail after retry exhaustion.
Failed items are captured here instead of being silently dropped, enabling:
  - Post-mortem analysis of failure patterns
  - Manual retry of specific items
  - Operational visibility into pipeline health
"""

import logging
import sqlite3
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# SQL for creating the DLQ table (also added to schema.py)
DLQ_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_dlq_status ON dead_letter_queue(status);
CREATE INDEX IF NOT EXISTS idx_dlq_paper_id ON dead_letter_queue(paper_id);
"""


class DeadLetterQueue:
    """
    SQLite-backed dead-letter queue for failed pipeline items.
    
    Thread-safe: Uses separate connection per operation with WAL mode.
    """
    
    def __init__(self, db_path: str):
        """
        Initialize DLQ with database path.
        
        Args:
            db_path: Path to SQLite database (typically data/sme.db)
        """
        self.db_path = db_path
        self._ensure_table()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-safe connection with WAL mode."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        return conn
    
    def _ensure_table(self):
        """Create DLQ table if it doesn't exist."""
        try:
            conn = self._get_connection()
            conn.executescript(DLQ_CREATE_SQL)
            conn.close()
            logger.info("[DLQ] Dead letter queue table initialized")
        except Exception as e:
            logger.error(f"[DLQ] Failed to create table: {e}")
            raise
    
    def push(self, paper_id: str, stage: str, error: str, retry_count: int = 0):
        """
        Push a failed item to the DLQ.
        
        Args:
            paper_id: Unique paper ID
            stage: Pipeline stage where failure occurred
            error: Error message
            retry_count: Number of retries attempted before giving up
        """
        try:
            conn = self._get_connection()
            conn.execute(
                """INSERT INTO dead_letter_queue 
                   (paper_id, stage, error, retry_count, created_at, status) 
                   VALUES (?, ?, ?, ?, ?, 'pending')""",
                (paper_id, stage, str(error)[:2000], retry_count, 
                 datetime.now().isoformat())
            )
            conn.commit()
            conn.close()
            logger.warning(
                f"[DLQ] Item pushed: paper_id={paper_id}, stage={stage}, "
                f"retries={retry_count}, error={str(error)[:200]}"
            )
        except Exception as e:
            # DLQ push must never crash the pipeline
            logger.error(f"[DLQ] CRITICAL: Failed to push to DLQ: {e}")
    
    def get_pending(self, limit: int = 50) -> List[Dict]:
        """Get pending DLQ items for potential retry."""
        try:
            conn = self._get_connection()
            rows = conn.execute(
                "SELECT * FROM dead_letter_queue WHERE status = 'pending' "
                "ORDER BY created_at ASC LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"[DLQ] Failed to fetch pending items: {e}")
            return []
    
    def mark_retried(self, dlq_id: int):
        """Mark a DLQ item as retried."""
        try:
            conn = self._get_connection()
            conn.execute(
                "UPDATE dead_letter_queue SET status = 'retried' WHERE id = ?",
                (dlq_id,)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"[DLQ] Failed to mark item {dlq_id} as retried: {e}")
    
    def mark_abandoned(self, dlq_id: int):
        """Mark a DLQ item as permanently abandoned."""
        try:
            conn = self._get_connection()
            conn.execute(
                "UPDATE dead_letter_queue SET status = 'abandoned' WHERE id = ?",
                (dlq_id,)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"[DLQ] Failed to mark item {dlq_id} as abandoned: {e}")
    
    def count_pending(self) -> int:
        """Count pending DLQ items."""
        try:
            conn = self._get_connection()
            count = conn.execute(
                "SELECT COUNT(*) FROM dead_letter_queue WHERE status = 'pending'"
            ).fetchone()[0]
            conn.close()
            return count
        except Exception as e:
            logger.error(f"[DLQ] Failed to count pending items: {e}")
            return -1
    
    def summary(self) -> Dict[str, int]:
        """Get summary counts by status and stage."""
        try:
            conn = self._get_connection()
            rows = conn.execute(
                "SELECT stage, status, COUNT(*) as cnt "
                "FROM dead_letter_queue GROUP BY stage, status"
            ).fetchall()
            conn.close()
            return {f"{row['stage']}/{row['status']}": row['cnt'] for row in rows}
        except Exception as e:
            logger.error(f"[DLQ] Failed to get summary: {e}")
            return {}
