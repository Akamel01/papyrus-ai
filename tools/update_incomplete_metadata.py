#!/usr/bin/env python
"""
Comprehensive Metadata Update Script

Updates ALL papers in sme.db with missing metadata fields (authors, year, venue).
Uses OpenAlex as primary source, with Semantic Scholar and local PDF metadata as fallbacks.

Usage:
    python tools/update_incomplete_metadata.py [--dry-run] [--limit N] [--source openalex|semantic]
"""

import os
import sys
import json
import logging
import argparse
import sqlite3
import time
import yaml
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.acquisition.api_clients.openalex import OpenAlexClient
from src.acquisition.api_clients.semantic_scholar import SemanticScholarClient

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
DB_PATH = Path("data/sme.db")
CONFIG_PATH = Path("config/acquisition_config.yaml")
BATCH_SIZE = 50
PROGRESS_KEY = "metadata_update_last_offset"
FAILURE_FILE = Path("data/metadata_update_failures.txt")


@dataclass
class UpdateStats:
    """Statistics for update operation."""
    total_incomplete: int = 0
    processed: int = 0
    updated: int = 0
    api_found: int = 0
    api_not_found: int = 0
    pdf_found: int = 0
    errors: int = 0


def load_config() -> Dict:
    """Load acquisition config."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)
    return {}


def get_total_incomplete(conn: sqlite3.Connection) -> int:
    """Get total count of incomplete papers."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM papers 
        WHERE doi IS NOT NULL AND doi != ''
        AND (
            authors IS NULL OR authors = '' OR authors = '[]' OR authors = 'null'
            OR year IS NULL
        )
    """)
    return cursor.fetchone()[0]


def get_progress(conn: sqlite3.Connection) -> int:
    """Get last processed offset from pipeline_state."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM pipeline_state WHERE key = ?", 
            (PROGRESS_KEY,)
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def save_progress(conn: sqlite3.Connection, offset: int):
    """Save progress to pipeline_state."""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO pipeline_state (key, value, updated_at) 
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
        """,
        (PROGRESS_KEY, str(offset), str(offset))
    )
    conn.commit()


def log_failure(doi: str, error: str):
    """Log failed DOI to file."""
    with open(FAILURE_FILE, "a", encoding="utf-8") as f:
        f.write(f"{doi}|{error}\n")


def extract_pdf_metadata(pdf_path: Path) -> Optional[Dict]:
    """Extract metadata from PDF properties."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        meta = doc.metadata
        
        title = meta.get('title', '').strip()
        author = meta.get('author', '').strip()
        
        # Parse year from creation date "D:20050114..."
        year = None
        creation_date = meta.get('creationDate', '')
        if creation_date.startswith('D:'):
            try:
                year = int(creation_date[2:6])
            except ValueError:
                pass
        
        doc.close()
        
        result = {}
        if title:
            result['title'] = title
        if author:
            result['authors'] = [author] # Format as list
        if year:
            result['year'] = year
            
        return result if result else None
    except Exception as e:
        logger.debug(f"PDF metadata extraction failed for {pdf_path}: {e}")
        return None


def update_paper_metadata(conn: sqlite3.Connection, paper_id: int, metadata: Dict) -> bool:
    """Update paper metadata in database."""
    try:
        cursor = conn.cursor()
        
        # Always update title if provided (API/PDF title is better than filename)
        cursor.execute(
            """
            UPDATE papers SET
                title = COALESCE(?, title),
                authors = COALESCE(?, authors),
                year = COALESCE(?, year),
                venue = COALESCE(?, venue)
            WHERE id = ?
            """,
            (
                metadata.get("title"),
                json.dumps(metadata.get("authors")) if metadata.get("authors") else None,
                metadata.get("year"),
                metadata.get("venue"),
                paper_id
            )
        )
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Update failed for paper {paper_id}: {e}")
        return False


def batch_lookup_openalex(client: OpenAlexClient, dois: List[str]) -> Dict[str, Dict]:
    """
    Batch lookup papers by DOI using OpenAlex API.
    
    Returns dict mapping DOI -> metadata.
    """
    results = {}
    
    if not dois:
        return results
    
    try:
        papers = client.search_by_dois(dois)
        
        for paper in papers:
            if paper and paper.doi:
                # Normalize DOI for comparison
                doi_normalized = paper.doi.lower()
                if doi_normalized.startswith("https://doi.org/"):
                    doi_normalized = doi_normalized.replace("https://doi.org/", "")
                
                results[doi_normalized] = {
                    "doi": paper.doi,
                    "title": paper.title,
                    "authors": paper.authors,
                    "year": paper.year,
                    "venue": paper.venue,
                    "citation_count": paper.citation_count
                }
    except Exception as e:
        logger.warning(f"OpenAlex batch lookup failed: {e}")
    
    return results


def batch_lookup_semantic_scholar(client: SemanticScholarClient, dois: List[str]) -> Dict[str, Dict]:
    """
    Batch lookup papers by DOI using Semantic Scholar API.
    """
    results = {}
    if not dois:
        return results
        
    try:
        papers = client.get_papers_by_dois(dois)
        for paper in papers:
            if paper and paper.doi:
                doi_normalized = paper.doi.lower()
                results[doi_normalized] = {
                    "doi": paper.doi,
                    "title": paper.title,
                    "authors": paper.authors,
                    "year": paper.year,
                    "venue": paper.venue,
                    "citation_count": paper.citation_count
                }
    except Exception as e:
        logger.warning(f"Semantic Scholar batch lookup failed: {e}")
        
    return results


def run_update(
    db_path: Path,
    dry_run: bool = False,
    limit: Optional[int] = None,
    resume: bool = True,
    use_fallback: bool = True
) -> UpdateStats:
    """Run the metadata update process."""
    stats = UpdateStats()
    
    # Load configuration
    config = load_config()
    openalex_key = config.get("acquisition", {}).get("apis", {}).get("openalex", {}).get("api_key")
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    # Get total incomplete
    stats.total_incomplete = get_total_incomplete(conn)
    logger.info(f"Found {stats.total_incomplete} papers with incomplete metadata")
    
    if stats.total_incomplete == 0:
        logger.info("All papers have complete metadata!")
        conn.close()
        return stats
    
    # Get starting offset
    start_offset = get_progress(conn) if resume else 0
    if start_offset > 0:
        logger.info(f"Resuming from offset {start_offset}")
    
    # Initialize Clients
    oa_client = OpenAlexClient(api_key=openalex_key)
    s2_client = SemanticScholarClient() # No key for s2 yet
    
    current_offset = start_offset
    papers_to_process = min(limit, stats.total_incomplete) if limit else stats.total_incomplete
    
    while stats.processed < papers_to_process:
        # Get batch of incomplete papers
        cursor = conn.cursor()
        query = """
            SELECT id, doi, pdf_path FROM papers 
            WHERE doi IS NOT NULL AND doi != ''
            AND (
                authors IS NULL OR authors = '' OR authors = '[]' OR authors = 'null'
                OR year IS NULL
            )
            ORDER BY id
            LIMIT ? OFFSET ?
        """
        cursor.execute(query, (BATCH_SIZE, current_offset))
        batch = [dict(row) for row in cursor.fetchall()]
        
        if not batch:
            logger.info("No more incomplete papers to process")
            break
        
        batch_num = (current_offset // BATCH_SIZE) + 1
        total_batches = (papers_to_process + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} papers)")
        
        # Prepare DOIs
        id_to_doi = {p['id']: p['doi'].lower() for p in batch if p['doi']}
        dois = list(id_to_doi.values())
        
        # 1. Batch lookup via OpenAlex
        metadata_map = batch_lookup_openalex(oa_client, dois)
        stats.api_found += len(metadata_map)
        
        # 2. Batch lookup via Semantic Scholar (Fallback for missing)
        missing_dois = [d for d in dois if d not in metadata_map]
        if missing_dois and use_fallback:
            s2_map = batch_lookup_semantic_scholar(s2_client, missing_dois)
            metadata_map.update(s2_map)
            stats.api_found += len(s2_map)
        
        # Process results
        for paper in batch:
            paper_id = paper['id']
            doi = paper['doi']
            pdf_rel_path = paper['pdf_path']
            doi_lower = doi.lower() if doi else None
            
            stats.processed += 1
            metadata = None
            
            # Check APIs
            if doi_lower and doi_lower in metadata_map:
                metadata = metadata_map[doi_lower]
            
            # 3. PDF Metadata Fallback (Local) - Last Resort
            if not metadata and pdf_rel_path:
                full_path = Path(pdf_rel_path)
                if not full_path.exists():
                     full_path = Path.cwd() / pdf_rel_path
                
                if full_path.exists():
                    pdf_meta = extract_pdf_metadata(full_path)
                    if pdf_meta:
                        metadata = pdf_meta
                        metadata['doi'] = doi 
                        stats.pdf_found += 1
            
            # Update Database
            if metadata:
                if not dry_run:
                    if update_paper_metadata(conn, paper_id, metadata):
                        stats.updated += 1
                    else:
                        stats.errors += 1
                else:
                    stats.updated += 1
            else:
                stats.api_not_found += 1
                if doi:
                    log_failure(doi, "Not found in any source")
        
        # Commit batch
        if not dry_run:
            conn.commit()
        
        # Save progress
        current_offset += len(batch)
        if not dry_run:
            save_progress(conn, current_offset)
        
        # Rate limiting
        time.sleep(0.1)
    
    conn.close()
    oa_client.close()
    s2_client.close()
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Update incomplete paper metadata in sme.db"
    )
    parser.add_argument(
        "--dry-run", 
        action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of papers to process"
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Start from beginning instead of resuming"
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Don't use Semantic Scholar/PDF as fallback"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=str(DB_PATH),
        help="Path to sme.db database"
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("METADATA UPDATE - INCOMPLETE RECORDS")
    logger.info("=" * 60)
    
    stats = run_update(
        db_path=Path(args.db_path),
        dry_run=args.dry_run,
        limit=args.limit,
        resume=not args.no_resume,
        use_fallback=not args.no_fallback
    )
    
    logger.info("=" * 60)
    logger.info("UPDATE COMPLETE")
    logger.info(f"  Total Incomplete: {stats.total_incomplete}")
    logger.info(f"  Processed:        {stats.processed}")
    logger.info(f"  Updated:          {stats.updated}")
    logger.info(f"  API Found:        {stats.api_found}")
    logger.info(f"  PDF Found:        {stats.pdf_found}")
    logger.info(f"  API/PDF Not Found:{stats.api_not_found}")
    logger.info(f"  Errors:           {stats.errors}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
