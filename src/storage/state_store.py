"""
SME Research Assistant - State Store

Handles persistent KV state (e.g. pipeline config) in SQLite.
"""

import json
import logging
from typing import Any, Optional
from .db import DatabaseManager

logger = logging.getLogger(__name__)

class StateStore:
    """Key-value store for pipeline state backed by SQLite."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        
    def set(self, key: str, value: Any):
        """Save a value (as JSON)."""
        json_val = json.dumps(value)
        query = """
        INSERT INTO pipeline_state (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """
        with self.db.get_connection() as conn:
            conn.execute(query, (key, json_val))
            
    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value."""
        query = "SELECT value FROM pipeline_state WHERE key = ?"
        with self.db.get_connection() as conn:
            row = conn.execute(query, (key,)).fetchone()
            if row:
                try:
                    return json.loads(row['value'])
                except json.JSONDecodeError:
                    return default
        return default
        
    def delete(self, key: str):
        """Remove a key."""
        query = "DELETE FROM pipeline_state WHERE key = ?"
        with self.db.get_connection() as conn:
            conn.execute(query, (key,))
