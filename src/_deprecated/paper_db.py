"""
DEPRECATED: This file was archived on 2026-02-02.

Reason: The PaperDatabase class is not used by any active code paths.
The streaming pipeline uses PaperStore from src/storage/paper_store.py instead.

If you need database access, use:
- PaperStore for paper CRUD operations
- APAReferenceResolver for reference lookups
"""

"""
SQLite-based paper database for the acquisition pipeline.
Replaces JSON-based discovery_cache.json for 100K+ scale operations.

Features:
- Atomic upserts (no full file rewrites)
- Indexed queries for fast status filtering
- Supports millions of records
- Built-in deduplication via UNIQUE constraints
"""

import sqlite3
import json
import logging
from pathlib import Path
from typing import Optional, List, Iterator, Dict, Any
from datetime import datetime
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class PaperRecord:
    """Represents a paper in the database."""
    doi: str
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    pdf_url: Optional[str] = None
    pdf_path: Optional[str] = None
    chunk_file: Optional[str] = None
    status: str = "discovered"
    source: str = "unknown"
    discovered_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        # Convert authors list to JSON string for storage
        d['authors'] = json.dumps(d['authors']) if d['authors'] else '[]'
        d['metadata'] = json.dumps(d['metadata']) if d['metadata'] else None
        return d
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'PaperRecord':
        """Create from database row."""
        return cls(
            doi=row['doi'],
            title=row['title'],
            authors=json.loads(row['authors']) if row['authors'] else [],
            year=row['year'],
            venue=row['venue'],
            abstract=row['abstract'],
            pdf_url=row['pdf_url'],
            pdf_path=row['pdf_path'],
            chunk_file=row['chunk_file'],
            status=row['status'],
            source=row['source'],
            discovered_at=row['discovered_at'],
            updated_at=row['updated_at'],
            metadata=json.loads(row['metadata']) if row['metadata'] else None
        )


class PaperDatabase:
    """
    SQLite-based paper storage for the acquisition pipeline.
    
    Replaces discovery_cache.json with atomic database operations
    suitable for 100K+ papers.
    
    Usage:
        db = PaperDatabase("data/papers.db")
        db.upsert(paper)
        for paper in db.get_by_status("discovered"):
            process(paper)
    """
    
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS papers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doi TEXT UNIQUE NOT NULL,
        title TEXT,
        authors TEXT,
        year INTEGER,
        venue TEXT,
        abstract TEXT,
        pdf_url TEXT,
        pdf_path TEXT,
        chunk_file TEXT,
        status TEXT DEFAULT 'discovered',
        source TEXT DEFAULT 'unknown',
        discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT,
        metadata TEXT
    );
    
    CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
    CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
    CREATE INDEX IF NOT EXISTS idx_papers_discovered_at ON papers(discovered_at);
    CREATE INDEX IF NOT EXISTS idx_papers_source ON papers(source);
    """
    
    def __init__(self, db_path: Path | str):
        """
        Initialize the paper database.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        logger.info(f"PaperDatabase initialized at {self.db_path}")
    
    def _init_schema(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.executescript(self.SCHEMA)
    
    @contextmanager
    def _get_connection(self):
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def upsert(self, paper: PaperRecord) -> bool:
        """
        Insert or update a paper record.
        
        Args:
            paper: Paper record to upsert
            
        Returns:
            True if inserted, False if updated
        """
        data = paper.to_dict()
        data['updated_at'] = datetime.utcnow().isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO papers (
                    doi, title, authors, year, venue, abstract,
                    pdf_url, pdf_path, chunk_file, status, source,
                    discovered_at, updated_at, metadata
                ) VALUES (
                    :doi, :title, :authors, :year, :venue, :abstract,
                    :pdf_url, :pdf_path, :chunk_file, :status, :source,
                    :discovered_at, :updated_at, :metadata
                )
                ON CONFLICT(doi) DO UPDATE SET
                    title = COALESCE(excluded.title, title),
                    authors = COALESCE(excluded.authors, authors),
                    year = COALESCE(excluded.year, year),
                    venue = COALESCE(excluded.venue, venue),
                    abstract = COALESCE(excluded.abstract, abstract),
                    pdf_url = COALESCE(excluded.pdf_url, pdf_url),
                    pdf_path = COALESCE(excluded.pdf_path, pdf_path),
                    chunk_file = COALESCE(excluded.chunk_file, chunk_file),
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    metadata = COALESCE(excluded.metadata, metadata)
                """,
                data
            )
            return cursor.rowcount > 0
    
    def upsert_batch(self, papers: List[PaperRecord]) -> int:
        """
        Insert or update multiple papers in a single transaction.
        
        Args:
            papers: List of paper records
            
        Returns:
            Number of papers affected
        """
        if not papers:
            return 0
        
        now = datetime.utcnow().isoformat()
        data_list = []
        for paper in papers:
            data = paper.to_dict()
            data['updated_at'] = now
            data_list.append(data)
        
        with self._get_connection() as conn:
            cursor = conn.executemany(
                """
                INSERT INTO papers (
                    doi, title, authors, year, venue, abstract,
                    pdf_url, pdf_path, chunk_file, status, source,
                    discovered_at, updated_at, metadata
                ) VALUES (
                    :doi, :title, :authors, :year, :venue, :abstract,
                    :pdf_url, :pdf_path, :chunk_file, :status, :source,
                    :discovered_at, :updated_at, :metadata
                )
                ON CONFLICT(doi) DO UPDATE SET
                    title = COALESCE(excluded.title, title),
                    pdf_path = COALESCE(excluded.pdf_path, pdf_path),
                    chunk_file = COALESCE(excluded.chunk_file, chunk_file),
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                data_list
            )
            return cursor.rowcount
    
    def get_by_status(self, status: str, limit: Optional[int] = None) -> Iterator[PaperRecord]:
        """
        Get papers by status (streaming).
        
        Args:
            status: Status to filter by
            limit: Optional limit on results
            
        Yields:
            PaperRecord objects
        """
        query = "SELECT * FROM papers WHERE status = ?"
        params = [status]
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            for row in cursor:
                yield PaperRecord.from_row(row)
    
    def update_status(self, doi: str, status: str, **fields) -> bool:
        """
        Update a paper's status and optional fields.
        
        Args:
            doi: Paper DOI
            status: New status
            **fields: Additional fields to update (pdf_path, chunk_file, etc.)
            
        Returns:
            True if updated, False if not found
        """
        set_clauses = ["status = ?", "updated_at = ?"]
        params = [status, datetime.utcnow().isoformat()]
        
        for key, value in fields.items():
            if key in ('pdf_path', 'chunk_file', 'pdf_url'):
                set_clauses.append(f"{key} = ?")
                params.append(value)
        
        params.append(doi)
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE papers SET {', '.join(set_clauses)} WHERE doi = ?",
                params
            )
            return cursor.rowcount > 0
    
    def exists(self, doi: str) -> bool:
        """Check if a paper exists by DOI."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM papers WHERE doi = ? LIMIT 1",
                (doi,)
            )
            return cursor.fetchone() is not None
    
    def get_by_doi(self, doi: str) -> Optional[PaperRecord]:
        """Get a paper by DOI."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM papers WHERE doi = ?",
                (doi,)
            )
            row = cursor.fetchone()
            return PaperRecord.from_row(row) if row else None
    
    def count(self, status: Optional[str] = None) -> int:
        """Count papers, optionally filtered by status."""
        with self._get_connection() as conn:
            if status:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM papers WHERE status = ?",
                    (status,)
                )
            else:
                cursor = conn.execute("SELECT COUNT(*) FROM papers")
            return cursor.fetchone()[0]
    
    def get_all_dois(self) -> set:
        """Get all DOIs in the database (for deduplication)."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT doi FROM papers")
            return {row['doi'] for row in cursor}
    
    def get_status_counts(self) -> Dict[str, int]:
        """Get counts of papers by status."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) as count FROM papers GROUP BY status"
            )
            return {row['status']: row['count'] for row in cursor}
    
    def delete_by_status(self, status: str) -> int:
        """Delete papers by status."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM papers WHERE status = ?",
                (status,)
            )
            return cursor.rowcount
    
    def vacuum(self):
        """Compact the database file."""
        with self._get_connection() as conn:
            conn.execute("VACUUM")


def migrate_json_to_sqlite(
    json_path: Path,
    db_path: Path,
    backup: bool = True
) -> int:
    """
    Migrate discovery_cache.json to SQLite database.
    
    Args:
        json_path: Path to discovery_cache.json
        db_path: Path to new SQLite database
        backup: Whether to rename JSON file as backup
        
    Returns:
        Number of papers migrated
    """
    if not json_path.exists():
        logger.warning(f"JSON file not found: {json_path}")
        return 0
    
    # Load JSON data
    with open(json_path, 'r', encoding='utf-8') as f:
        papers_data = json.load(f)
    
    logger.info(f"Migrating {len(papers_data)} papers from JSON to SQLite...")
    
    # Create database
    db = PaperDatabase(db_path)
    
    # Convert and insert papers
    records = []
    for p in papers_data:
        record = PaperRecord(
            doi=p.get('doi', p.get('identifier', '')),
            title=p.get('title'),
            authors=p.get('authors', []),
            year=p.get('year'),
            venue=p.get('venue'),
            abstract=p.get('abstract'),
            pdf_url=p.get('pdf_url'),
            pdf_path=p.get('pdf_path'),
            chunk_file=p.get('chunk_file'),
            status=p.get('status', 'discovered'),
            source=p.get('source', 'unknown'),
            discovered_at=p.get('discovered_at'),
            metadata=p.get('metadata')
        )
        if record.doi:  # Skip records without DOI
            records.append(record)
    
    # Batch insert
    count = db.upsert_batch(records)
    
    # Backup JSON file
    if backup:
        backup_path = json_path.with_suffix('.json.bak')
        json_path.rename(backup_path)
        logger.info(f"Backed up JSON to: {backup_path}")
    
    logger.info(f"Migration complete: {count} papers in SQLite database")
    return count
