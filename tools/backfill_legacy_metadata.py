#!/usr/bin/env python
"""
Legacy Paper Metadata Backfill Script

Populates sme.db with metadata for legacy papers that were processed
by migrate_vectors.py but never registered in the database.

This enables DOI-based APA reference lookup for all papers.

Usage:
    python tools/backfill_legacy_metadata.py [--dry-run] [--limit N]
"""

import os
import sys
import json
import logging
import argparse
import sqlite3
from pathlib import Path
from typing import List, Dict, Set, Optional
from dataclasses import dataclass

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.acquisition.api_clients.openalex import OpenAlexClient
from src.ingestion.pdf_parser import extract_doi_from_filename

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
PAPERS_DIR = Path("DataBase/Papers")
DB_PATH = Path("data/sme.db")
PROGRESS_KEY = "legacy_backfill_last_index"
FAILURE_FILE = Path("data/backfill_failures.txt")
BATCH_SIZE = 50  # DOIs per OpenAlex request


@dataclass
class BackfillStats:
    """Statistics for backfill operation."""
    total_pdfs: int = 0
    dois_extracted: int = 0
    already_in_db: int = 0
    api_lookups: int = 0
    inserted: int = 0
    failed: int = 0
    no_doi: int = 0


def get_existing_dois(db_path: Path) -> Set[str]:
    """Get set of DOIs already in database."""
    if not db_path.exists():
        return set()
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT doi FROM papers WHERE doi IS NOT NULL")
    dois = {row[0] for row in cursor.fetchall()}
    conn.close()
    return dois


def get_progress(db_path: Path) -> int:
    """Get last processed index from pipeline_state."""
    if not db_path.exists():
        return 0
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM pipeline_state WHERE key = ?", 
            (PROGRESS_KEY,)
        )
        row = cursor.fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def save_progress(db_path: Path, index: int):
    """Save progress to pipeline_state."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO pipeline_state (key, value, updated_at) 
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
        """,
        (PROGRESS_KEY, str(index), str(index))
    )
    conn.commit()
    conn.close()


def log_failure(doi: str, error: str):
    """Log failed DOI to file."""
    with open(FAILURE_FILE, "a", encoding="utf-8") as f:
        f.write(f"{doi}|{error}\n")


def insert_paper(conn: sqlite3.Connection, metadata: Dict) -> bool:
    """Insert paper metadata into database."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO papers (
                unique_id, doi, title, authors, year, venue, 
                status, source, citation_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"doi:{metadata['doi'].lower()}",
                metadata["doi"],
                metadata.get("title", ""),
                json.dumps(metadata.get("authors", [])),
                metadata.get("year"),
                metadata.get("venue"),
                "embedded",  # Already embedded by migrate_vectors
                "backfill",
                metadata.get("citation_count", 0)
            )
        )
        return True
    except sqlite3.IntegrityError:
        # Duplicate - already exists
        return False
    except Exception as e:
        logger.error(f"Insert failed for {metadata.get('doi')}: {e}")
        return False


def batch_lookup_openalex(client: OpenAlexClient, dois: List[str]) -> Dict[str, Dict]:
    """
    Batch lookup papers by DOI using OpenAlex API.
    
    Args:
        client: OpenAlexClient instance
        dois: List of DOIs to look up
        
    Returns:
        Dictionary mapping DOI -> metadata dict
    """
    results = {}
    
    if not dois:
        return results
    
    try:
        # OpenAlex filter format: doi:10.1234/abc|10.5678/xyz
        doi_filter = "|".join(dois)
        
        # Use the client's search method with DOI filter
        # Note: OpenAlex allows filtering by multiple DOIs
        papers = client.search_by_dois(dois)
        
        for paper in papers:
            if paper and paper.doi:
                results[paper.doi] = {
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


def run_backfill(
    papers_dir: Path,
    db_path: Path,
    dry_run: bool = False,
    limit: Optional[int] = None,
    resume: bool = True
) -> BackfillStats:
    """
    Run the legacy metadata backfill process.
    
    Args:
        papers_dir: Directory containing legacy PDFs
        db_path: Path to sme.db
        dry_run: If True, don't actually insert
        limit: Optional limit on papers to process
        resume: If True, resume from last saved progress
        
    Returns:
        BackfillStats with operation statistics
    """
    stats = BackfillStats()
    
    # Get existing DOIs
    existing_dois = get_existing_dois(db_path)
    logger.info(f"Found {len(existing_dois)} DOIs already in database")
    
    # List all PDFs
    pdf_files = sorted(list(papers_dir.glob("*.pdf")))
    stats.total_pdfs = len(pdf_files)
    logger.info(f"Found {stats.total_pdfs} PDF files in {papers_dir}")
    
    if limit:
        pdf_files = pdf_files[:limit]
        logger.info(f"Limited to first {limit} files")
    
    # Resume from progress
    start_index = get_progress(db_path) if resume else 0
    if start_index > 0:
        logger.info(f"Resuming from index {start_index}")
        pdf_files = pdf_files[start_index:]
    
    # Extract DOIs from filenames
    doi_to_file = {}
    for pdf_file in pdf_files:
        doi = extract_doi_from_filename(pdf_file.name)
        if doi:
            # Skip if already in DB
            if doi in existing_dois:
                stats.already_in_db += 1
                continue
            doi_to_file[doi] = pdf_file
            stats.dois_extracted += 1
        else:
            stats.no_doi += 1
    
    logger.info(f"Extracted {stats.dois_extracted} DOIs to look up")
    logger.info(f"Skipped {stats.already_in_db} already in DB, {stats.no_doi} without DOI")
    
    if dry_run:
        logger.info("[DRY RUN] Would look up and insert papers")
        return stats
    
    # Initialize OpenAlex client
    client = OpenAlexClient()
    
    # Open DB connection
    conn = sqlite3.connect(str(db_path))
    
    # Process in batches
    dois_list = list(doi_to_file.keys())
    total_batches = (len(dois_list) + BATCH_SIZE - 1) // BATCH_SIZE
    
    for batch_idx in range(0, len(dois_list), BATCH_SIZE):
        batch_num = batch_idx // BATCH_SIZE + 1
        batch_dois = dois_list[batch_idx:batch_idx + BATCH_SIZE]
        
        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch_dois)} DOIs)")
        
        # Lookup via OpenAlex
        metadata_map = batch_lookup_openalex(client, batch_dois)
        stats.api_lookups += 1
        
        # Insert results
        for doi in batch_dois:
            if doi in metadata_map:
                if insert_paper(conn, metadata_map[doi]):
                    stats.inserted += 1
                else:
                    stats.failed += 1
            else:
                # API didn't return this DOI
                log_failure(doi, "Not found in OpenAlex")
                stats.failed += 1
        
        # Commit batch
        conn.commit()
        
        # Save progress
        save_progress(db_path, start_index + batch_idx + len(batch_dois))
    
    conn.close()
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Backfill sme.db with metadata for legacy papers"
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
        "--papers-dir",
        type=str,
        default=str(PAPERS_DIR),
        help="Directory containing PDF files"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=str(DB_PATH),
        help="Path to sme.db database"
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("LEGACY PAPER METADATA BACKFILL")
    logger.info("=" * 60)
    
    if args.dry_run:
        logger.info("[DRY RUN MODE]")
    
    stats = run_backfill(
        papers_dir=Path(args.papers_dir),
        db_path=Path(args.db_path),
        dry_run=args.dry_run,
        limit=args.limit,
        resume=not args.no_resume
    )
    
    logger.info("=" * 60)
    logger.info("BACKFILL COMPLETE")
    logger.info(f"  Total PDFs:      {stats.total_pdfs}")
    logger.info(f"  DOIs Extracted:  {stats.dois_extracted}")
    logger.info(f"  Already in DB:   {stats.already_in_db}")
    logger.info(f"  API Lookups:     {stats.api_lookups}")
    logger.info(f"  Inserted:        {stats.inserted}")
    logger.info(f"  Failed:          {stats.failed}")
    logger.info(f"  No DOI in name:  {stats.no_doi}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
