"""
SME Research Assistant - Database Manager

Handles SQLite connection and initialization.
"""

import sqlite3
import logging
import json
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any, Generator
from contextlib import contextmanager
from .schema import SCHEMA_SQL

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Manages SQLite database connection and operations."""
    
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._init_db()
        
    def _init_db(self):
        """Initialize database schema if it doesn't exist."""
        # Ensure parent dir exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with self.get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            
    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a database connection context."""
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            # Increase timeout to 30s for busy periods
            conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
            
            # Enable WAL mode for concurrency
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
            except Exception:
                # Fallback if PRAGMA fails (e.g. strict permissions), though unlikely
                pass
                
            # Enable Row factory for dict-like access
            conn.row_factory = sqlite3.Row
            self._local.conn = conn

        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
            
    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a single query (helper)."""
        with self.get_connection() as conn:
            return conn.execute(query, params)
