#!/usr/bin/env python
"""
Migration script to import legacy PDF files from DataBase/Papers into the SQLite database.
Sets status to 'legacy' to ensure deduplication (PaperDiscoverer checks existence)
but prevents re-processing by active pipeline stages.
"""

import sys
import os
import sqlite3
import logging
from pathlib import Path
from typing import List, Tuple
from tqdm import tqdm

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.storage import DatabaseManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def parse_filename(filename: str) -> Tuple[str, str, str]:
    """
    Parse filename to extract ID type and value.
    Returns (unique_id, doi, arxiv_id)
    """
    # Remove extension
    stem = Path(filename).stem
    
    if stem.startswith("arXiv-"):
        # Format: arXiv-2301.12345
        # Clean: 2301.12345
        aid = stem.replace("arXiv-", "")
        # Remove version if present (v1)
        import re
        aid = re.sub(r"v\d+$", "", aid)
        return f"arxiv:{aid.lower()}", None, aid
        
    elif "10." in stem:
        # Likely a DOI (e.g. 10.1109_CVPR.2023.12345)
        # Underscores usually replace slashes in filenames
        doi = stem.replace("_", "/")
        
        # Heuristic: Find start of DOI (10.)
        idx = doi.find("10.")
        if idx != -1:
            doi = doi[idx:]
            
        return f"doi:{doi.lower()}", doi, None
        
    else:
        # Fallback: Treat as title or other ID
        # Normalize
        norm = stem.lower()
        return f"file:{norm}", None, None

def migrate_legacy_papers(db_path: str = "data/sme.db", papers_dir: str = "DataBase/Papers"):
    db_path = Path(db_path)
    papers_path = Path(papers_dir)
    
    if not papers_path.exists():
        logger.error(f"Papers directory not found: {papers_path}")
        return
        
    logger.info(f"Scanning {papers_path}...")
    files = list(papers_path.glob("*.pdf"))
    logger.info(f"Found {len(files)} PDF files")
    
    db_manager = DatabaseManager(str(db_path))
    
    entries = []
    
    for f in tqdm(files, desc="Parsing filenames"):
        unique_id, doi, arxiv_id = parse_filename(f.name)
        
        # Define fields
        # status='legacy' prevents pipeline from processing but ensures deduplication
        entry = (
            unique_id,
            doi,
            arxiv_id,
            None, # openalex_id
            f.stem, # Title (fallback to filename)
            '[]', # authors (json list)
            None, # year
            None, # venue
            None, # abstract
            None, # pdf_url
            'legacy', # status
            str(f), # pdf_path (we store it, even if user deletes later, record implies it existed)
            0, # citation_count
            'legacy_import' # source
        )
        entries.append(entry)
        
    logger.info(f"Inserting {len(entries)} records into database...")
    
    query = """
    INSERT OR IGNORE INTO papers (
        unique_id, doi, arxiv_id, openalex_id, title, authors, year,
        venue, abstract, pdf_url, status, pdf_path, citation_count, source
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    
    try:
        with db_manager.get_connection() as conn:
            conn.executemany(query, entries)
            logger.info("Migration completed successfully.")
            
            # Verify count
            count = conn.execute("SELECT COUNT(*) FROM papers WHERE status='legacy'").fetchone()[0]
            logger.info(f"Total legacy papers in DB: {count}")
            
    except Exception as e:
        logger.error(f"Migration failed: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Import legacy papers to SQLite")
    parser.add_argument("--db", default="data/sme.db", help="Path to DB")
    parser.add_argument("--dir", default="DataBase/Papers", help="Path to Papers dir")
    
    args = parser.parse_args()
    migrate_legacy_papers(args.db, args.dir)
