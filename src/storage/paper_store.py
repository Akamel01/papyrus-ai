"""
SME Research Assistant - Paper Store

Handles data access for Paper objects in SQLite.
"""

import json
import logging
import sqlite3
import time
from typing import List, Optional, Dict, Any, Set
from .db import DatabaseManager
from ..acquisition.paper_discoverer import DiscoveredPaper

logger = logging.getLogger(__name__)

class PaperStore:
    """Repository for accessing paper data."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self._ensure_schema_compatibility()

    def _ensure_schema_compatibility(self):
        """Ensure the database schema is up to date (migration)."""
        try:
            with self.db.get_connection() as conn:
                columns = [r[1] for r in conn.execute("PRAGMA table_info(papers)").fetchall()]
                if 'metadata' not in columns:
                    logger.info("Migrating schema: Adding 'metadata' column to papers table")
                    conn.execute("ALTER TABLE papers ADD COLUMN metadata TEXT")
                if 'chunk_file' not in columns:
                    logger.info("Migrating schema: Adding 'chunk_file' column to papers table")
                    conn.execute("ALTER TABLE papers ADD COLUMN chunk_file TEXT")
                if 'apa_reference' not in columns:
                    logger.info("Migrating schema: Adding 'apa_reference' column to papers table")
                    conn.execute("ALTER TABLE papers ADD COLUMN apa_reference TEXT")
                # Manual Import feature columns
                if 'file_checksum' not in columns:
                    logger.info("Migrating schema: Adding 'file_checksum' column to papers table")
                    conn.execute("ALTER TABLE papers ADD COLUMN file_checksum TEXT")
                if 'import_source' not in columns:
                    logger.info("Migrating schema: Adding 'import_source' column to papers table")
                    conn.execute("ALTER TABLE papers ADD COLUMN import_source TEXT DEFAULT 'api'")
                # Ensure index exists for fast checksum lookups
                conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_file_checksum ON papers(file_checksum)")
        except Exception as e:
            logger.error(f"Schema migration failed: {e}")

    def _row_to_paper(self, row: Any) -> DiscoveredPaper:
        """Convert DB row to DiscoveredPaper object."""
        try:
            return DiscoveredPaper(
                doi=row['doi'],
                arxiv_id=row['arxiv_id'],
                openalex_id=row['openalex_id'],
                title=row['title'],
                authors=json.loads(row['authors']) if row['authors'] else [],
                year=row['year'],
                venue=row['venue'],
                abstract=row['abstract'],
                pdf_url=row['pdf_url'],
                citation_count=row['citation_count'],
                source=row['source'],
                status=row['status'],
                pdf_path=row['pdf_path'],
                chunk_file=row['chunk_file'],
                metadata=json.loads(row['metadata']) if row['metadata'] else {},
                apa_reference=row['apa_reference'] if 'apa_reference' in row.keys() else None,
                file_checksum=row['file_checksum'] if 'file_checksum' in row.keys() else None,
                import_source=row['import_source'] if 'import_source' in row.keys() else 'api'
            )
        except Exception as e:
            logger.error(f"Error parsing row {row.get('unique_id', 'UNKNOWN')}: {e}")
            return None
            
    def _execute_with_retry(self, query: str, params: Any, operation_name: str, max_duration: int = 300, is_many: bool = False) -> int:
        """
        Execute a query with infinite backoff retry for transient SQLite database locks, 
        capped at max_duration (default 5 minutes).
        Returns the rowcount of the executed statement.
        """
        start_time = time.time()
        attempt = 1
        
        while True:
            try:
                with self.db.get_connection() as conn:
                    if is_many:
                        cursor = conn.executemany(query, params)
                    else:
                        cursor = conn.execute(query, params)
                    return cursor.rowcount
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e):
                    elapsed = time.time() - start_time
                    if elapsed > max_duration:
                        logger.error(f"[DB-LOCK-TIMEOUT] Gave up on '{operation_name}' after {elapsed:.1f}s locked. Error: {e}")
                        raise
                    
                    # Exponential backoff: 2s, 4s, 6s... capped at 15s max per sleep
                    sleep_time = min(2.0 * attempt, 15.0)
                    logger.warning(f"[PaperStore] DB locked during '{operation_name}'. Retrying in {sleep_time:.1f}s (elapsed {elapsed:.1f}s)")
                    time.sleep(sleep_time)
                    attempt += 1
                else:
                    logger.error(f"[PaperStore] OperationalError during '{operation_name}': {e}")
                    raise
            except Exception as e:
                # Let unique constraint violations bubble up without error logging here, 
                # they are handled neatly by the caller (like add_paper)
                if "UNIQUE constraint failed" not in str(e):
                    logger.error(f"[PaperStore] Error during '{operation_name}': {e}")
                raise
                
    def add_paper(self, paper: DiscoveredPaper) -> bool:
        """
        Add a paper if it doesn't represent a duplicate.
        Returns True if added, False if duplicate unique_id exists.
        """
        query = """
        INSERT INTO papers (
            unique_id, doi, arxiv_id, openalex_id, title, authors, year,
            venue, abstract, pdf_url, status, pdf_path, citation_count, source, metadata, apa_reference,
            file_checksum, import_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            self._execute_with_retry(
                query,
                (
                    paper.unique_id,
                    paper.doi,
                    paper.arxiv_id,
                    paper.openalex_id,
                    paper.title,
                    json.dumps(paper.authors),
                    paper.year,
                    paper.venue,
                    paper.abstract,
                    paper.pdf_url,
                    paper.status,
                    paper.pdf_path,
                    paper.citation_count,
                    paper.source,
                    json.dumps(paper.metadata) if paper.metadata else None,
                    paper.apa_reference,
                    paper.file_checksum,
                    paper.import_source
                ),
                f"add paper {paper.unique_id}"
            )
            return True
        except Exception as e:
            # Unique constraint violation or other error
            if "UNIQUE constraint failed" not in str(e):
                logger.error(f"Failed to add paper {paper.unique_id}: {e}")
            return False

    def add_papers_batch(self, papers: List[DiscoveredPaper]) -> int:
        """
        Add multiple papers efficiently.
        Returns number of papers actually added (skipping duplicates).
        """
        if not papers:
            return 0
            
        # Use INSERT OR IGNORE to handle duplicates gracefully in batch
        query = """
        INSERT OR IGNORE INTO papers (
            unique_id, doi, arxiv_id, openalex_id, title, authors, year,
            venue, abstract, pdf_url, status, pdf_path, citation_count, source, metadata, apa_reference,
            file_checksum, import_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        data = [
            (
                p.unique_id,
                p.doi,
                p.arxiv_id,
                p.openalex_id,
                p.title,
                json.dumps(p.authors),
                p.year,
                p.venue,
                p.abstract,
                p.pdf_url,
                p.status,
                p.pdf_path,
                p.citation_count,
                p.source,
                json.dumps(p.metadata) if p.metadata else None,
                p.apa_reference,
                p.file_checksum,
                p.import_source
            )
            for p in papers
        ]
        
        try:
            return self._execute_with_retry(
                query, 
                data, 
                f"batch add {len(papers)} papers", 
                is_many=True
            )
        except Exception as e:
            logger.error(f"Failed to batch add papers: {e}")
            return 0

    def get_paper(self, unique_id: str) -> Optional[DiscoveredPaper]:
        """Retrieve a paper by unique_id."""
        query = "SELECT * FROM papers WHERE unique_id = ?"
        with self.db.get_connection() as conn:
            row = conn.execute(query, (unique_id,)).fetchone()
            if row:
                return self._row_to_paper(row)
        return None
        
    def status_exists(self, unique_id: str) -> bool:
        """Check if paper exists by unique_id."""
        query = "SELECT 1 FROM papers WHERE unique_id = ?"
        with self.db.get_connection() as conn:
            return conn.execute(query, (unique_id,)).fetchone() is not None

    def update_status(self, unique_id: str, status: str, error: Optional[str] = None, pdf_path: Optional[str] = None, chunk_file: Optional[str] = None):
        """Update paper status and optional fields."""
        query = "UPDATE papers SET status = ?, updated_at = CURRENT_TIMESTAMP"
        params = [status]
        
        if error is not None:
            query += ", error_message = ?"
            params.append(error)
            
        if pdf_path is not None:
            query += ", pdf_path = ?"
            params.append(pdf_path)
            
        if chunk_file is not None:
            query += ", chunk_file = ?"
            params.append(chunk_file)
            
        query += " WHERE unique_id = ?"
        params.append(unique_id)
        
        try:
            self._execute_with_retry(query, tuple(params), f"update status to '{status}' for {unique_id}")
        except Exception as e:
            logger.error(f"Failed to update status for {unique_id}: {e}")
            raise

    def update_metadata(self, unique_id: str, apa_reference: str, metadata: Optional[Dict] = None):
        """Update paper metadata and apa_reference."""
        query = "UPDATE papers SET apa_reference = ?, updated_at = CURRENT_TIMESTAMP"
        params = [apa_reference]
        
        if metadata:
            query += ", metadata = ?"
            params.append(json.dumps(metadata))
            
        query += " WHERE unique_id = ?"
        params.append(unique_id)
        
        try:
            self._execute_with_retry(query, tuple(params), f"update metadata for {unique_id}")
        except Exception as e:
            logger.error(f"Failed to update metadata for {unique_id}: {e}")
            raise

    def reset_transient_status(self, target_status: str, new_status: str) -> int:
        """
        Reset papers from a transient state (e.g., 'chunked') to a safe state (e.g., 'downloaded').
        Used for recovering from crashes where in-memory state was lost.
        """
        query = "UPDATE papers SET status = ? WHERE status = ?"
        try:
            count = self._execute_with_retry(query, (new_status, target_status), f"reset status from {target_status} to {new_status}")
            if count > 0:
                logger.info(f"Reset {count} papers from '{target_status}' to '{new_status}'")
            return count
        except Exception as e:
            logger.error(f"Failed to reset status from {target_status} to {new_status}: {e}")
            return 0

    def get_min_id_for_status(self, status: str) -> int:
        """Get the minimum ID for papers with a specific status."""
        query = "SELECT MIN(id) FROM papers WHERE status = ?"
        try:
            with self.db.get_connection() as conn:
                result = conn.execute(query, (status,)).fetchone()
                # Return result[0] if exists, else 0. 
                # If result[0] is None (no rows), return 0.
                return result[0] if result and result[0] is not None else 0
        except Exception as e:
            logger.error(f"Failed to get min ID for status {status}: {e}")
            return 0

    def get_discovered_papers_since(self, last_id: int, limit: int = 100) -> List[tuple[int, DiscoveredPaper]]:
        """
        Get papers with 'discovered' status created after last_id.
        Returns list of (row_id, DiscoveredPaper).
        Optimized for streaming.
        """
        query = """
        SELECT * FROM papers 
        WHERE status = 'discovered' AND id > ? 
        ORDER BY id ASC 
        LIMIT ?
        """
        results = []
        with self.db.get_connection() as conn:
            rows = conn.execute(query, (last_id, limit)).fetchall()
            for row in rows:
                paper = self._row_to_paper(row)
                if paper:
                    results.append((row['id'], paper))
        return results

    def get_newest_discovered_papers(self, limit: int = 100) -> List[tuple[int, DiscoveredPaper]]:
        """
        Get the newest papers with 'discovered' status.
        Always returns the absolute newest papers regardless of previous calls.
        Used for "always newest" download ordering.
        """
        query = """
        SELECT * FROM papers 
        WHERE status = 'discovered'
        ORDER BY id DESC 
        LIMIT ?
        """
        results = []
        with self.db.get_connection() as conn:
            rows = conn.execute(query, (limit,)).fetchall()
            for row in rows:
                paper = self._row_to_paper(row)
                if paper:
                    results.append((row['id'], paper))
        return results


        


    def get_papers_by_status(self, status: str, limit: int = 100) -> List[DiscoveredPaper]:
        """Get papers with specific status."""
        query = "SELECT * FROM papers WHERE status = ? LIMIT ?"
        with self.db.get_connection() as conn:
            rows = conn.execute(query, (status, limit)).fetchall()
            return [self._row_to_paper(r) for r in rows]
            
    def get_all_dois(self) -> List[str]:
        """Get list of all DOIs in the DB."""
        query = "SELECT doi FROM papers WHERE doi IS NOT NULL"
        with self.db.get_connection() as conn:
            return [r[0] for r in conn.execute(query).fetchall()]

    def get_all_unique_ids(self) -> Set[str]:
        """Get set of all unique_ids in the DB."""
        query = "SELECT unique_id FROM papers"
        with self.db.get_connection() as conn:
            return {r[0] for r in conn.execute(query).fetchall()}

    def find_by_checksum(self, checksum: str) -> Optional[DiscoveredPaper]:
        """Find paper by file checksum."""
        query = "SELECT * FROM papers WHERE file_checksum = ?"
        with self.db.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (checksum,)).fetchone()
            if row:
                return self._row_to_paper(row)
        return None

    def find_by_doi(self, doi: str) -> Optional[DiscoveredPaper]:
        """Find paper by DOI."""
        if not doi: return None
        query = "SELECT * FROM papers WHERE LOWER(doi) = LOWER(?)"
        with self.db.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (doi,)).fetchone()
            if row:
                return self._row_to_paper(row)
        return None

    def find_by_title(self, title: str) -> Optional[DiscoveredPaper]:
        """Find paper by Title (normalized - whitespace collapsed)."""
        if not title: return None

        # Normalize whitespace before comparison
        normalized_title = ' '.join(title.strip().split())
        query = "SELECT * FROM papers WHERE LOWER(TRIM(title)) = LOWER(?)"
        with self.db.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, (normalized_title,)).fetchone()
            if row:
                return self._row_to_paper(row)
        return None

    def upgrade_to_manual_import(self, unique_id: str, pdf_path: str, checksum: str):
        """
        Convert an existing record to a manual import by updating path and checksum.
        Changes source to 'manual_import' and resets status to 'downloaded' for re-processing.
        """
        query = """
        UPDATE papers
        SET pdf_path = ?, file_checksum = ?, source = 'manual_import', import_source = 'manual_import',
            status = 'downloaded', updated_at = CURRENT_TIMESTAMP
        WHERE unique_id = ?
        """
        try:
            self._execute_with_retry(query, (pdf_path, checksum, unique_id), f"upgrade {unique_id} to manual import")
            logger.info(f"Upgraded paper {unique_id} to manual import source (PDF: {pdf_path})")
        except Exception as e:
            logger.error(f"Failed to upgrade paper {unique_id} to manual import: {e}")
            raise

