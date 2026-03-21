import csv
import sqlite3
import json
import logging
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Ensure import_legacy_papers is importable
sys.path.insert(0, os.path.dirname(__file__))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

REAL_DB_PATH = Path("data/sme.db")
DUMP_PATH = Path("DataBase/openalex_database.txt")

def normalize_doi(doi: str) -> str:
    """Normalize DOI string."""
    if not doi:
        return ""
    doi = doi.strip().lower()
    if doi.startswith("doi:"):
        doi = doi[4:]
    if doi.startswith("https://doi.org/"):
        doi = doi.replace("https://doi.org/", "")
    if doi.startswith("http://doi.org/"):
        doi = doi.replace("http://doi.org/", "")
    return doi

def parse_authors(author_str: str) -> str:
    """Parse semicolon separated authors into JSON list."""
    if not author_str:
        return "[]"
    authors = [a.strip() for a in author_str.split(';') if a.strip()]
    return json.dumps(authors)

def check_and_restore_db():
    start_fresh = False
    
    if not REAL_DB_PATH.exists():
        logger.warning(f"Production DB {REAL_DB_PATH} missing. Starting migration...")
        start_fresh = True
    else:
        # Check if empty
        try:
            conn = sqlite3.connect(REAL_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT count(*) FROM papers")
            cnt = c.fetchone()[0]
            if cnt == 0:
                logger.warning(f"Production DB {REAL_DB_PATH} is empty. Starting migration...")
                start_fresh = True
            conn.close()
        except Exception:
            logger.warning(f"Production DB {REAL_DB_PATH} check failed. Starting migration...")
            start_fresh = True
            
    if start_fresh:
        try:
            from import_legacy_papers import migrate_legacy_papers
            migrate_legacy_papers(db_path=str(REAL_DB_PATH), papers_dir="DataBase/Papers")
        except ImportError:
            logger.error("Could not import migrate_legacy_papers tool.")
            return False
            
    return True

def enrich_db():
    if not check_and_restore_db():
        logger.error("Database check/restore failed.")
        return

    logger.info(f"Connecting to {REAL_DB_PATH}...")
    conn = sqlite3.connect(REAL_DB_PATH)
    cursor = conn.cursor()

    logger.info(f"Reading {DUMP_PATH} for Metadata Enrichment (UPDATE ONLY)...")
    
    stats = {
        "processed": 0,
        "updated": 0,
        "skipped_no_doi": 0,
        "not_in_db": 0
    }

    try:
        # Load existing DOIs for fast check
        logger.info("loading existing DOIs...")
        cursor.execute("SELECT lower(doi) FROM papers WHERE doi IS NOT NULL")
        existing_dois = {r[0] for r in cursor.fetchall()}
        logger.info(f"Found {len(existing_dois)} existing DOIs in DB.")

        with open(DUMP_PATH, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            batch = []
            BATCH_SIZE = 1000
            
            for row in reader:
                stats["processed"] += 1
                
                raw_doi = row.get("DOI", "")
                if not raw_doi:
                    stats["skipped_no_doi"] += 1
                    continue
                
                doi = normalize_doi(raw_doi)
                
                if doi not in existing_dois:
                    stats["not_in_db"] += 1
                    continue
                
                # DOI exists in DB, prepare update
                title = row.get("Title", "")
                abstract = row.get("Abstract Note", "")
                year_str = row.get("Publication Year", "")
                year = int(year_str) if year_str and year_str.isdigit() else None
                venue = row.get("Publication Title", "") or row.get("Journal Abbreviation", "")
                # url = row.get("Url", "") # Excluded because 'url' column doesn't exist
                authors_json = parse_authors(row.get("Author", ""))
                
                now = datetime.utcnow().isoformat()
                
                batch.append((
                    title, abstract, authors_json, year, venue, now,
                    doi # WHERE clause
                ))
                
                if len(batch) >= BATCH_SIZE:
                    _execute_batch(cursor, batch)
                    conn.commit()
                    stats["updated"] += len(batch)
                    batch = []
                    print(f"Processed {stats['processed']}...", end='\r')
            
            if batch:
                _execute_batch(cursor, batch)
                conn.commit()
                stats["updated"] += len(batch)

    except Exception as e:
        logger.error(f"Error reading dump: {e}")
        conn.rollback()
    finally:
        conn.close()

    logger.info("\nEnrichment Complete!")
    logger.info(f"Total Dump Records: {stats['processed']}")
    logger.info(f"Updated (Found in DB): {stats['updated']}")
    logger.info(f"Skipped (Not in DB): {stats['not_in_db']}")
    logger.info(f"Skipped (No DOI): {stats['skipped_no_doi']}")

def _execute_batch(cursor, batch):
    sql = """
    UPDATE papers SET
        title = ?,
        abstract = ?,
        authors = ?,
        year = ?,
        venue = ?,
        updated_at = ?
    WHERE lower(doi) = lower(?)
    """
    try:
        cursor.executemany(sql, batch)
    except sqlite3.Error as e:
        logger.error(f"Batch update error: {e}")

if __name__ == "__main__":
    enrich_db()
