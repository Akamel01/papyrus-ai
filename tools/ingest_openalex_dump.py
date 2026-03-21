import csv
import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DB_PATH = Path("sme.db")
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
    # Split by semicolon and strip
    authors = [a.strip() for a in author_str.split(';') if a.strip()]
    return json.dumps(authors)

def ingest_dump():
    if not DUMP_PATH.exists():
        logger.error(f"Dump file not found at {DUMP_PATH}")
        return

    logger.info(f"Connecting to {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Ensure Papers table exists (it should)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY,
            title TEXT,
            abstract TEXT,
            authors TEXT,
            year INTEGER,
            venue TEXT,
            doi TEXT UNIQUE,
            url TEXT,
            pdf_path TEXT,
            is_open_access INTEGER,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)

    logger.info(f"Reading {DUMP_PATH}...")
    
    # Check CSV Dialect or just assume standard
    # The file seemed to have header and quotechar '"'
    
    stats = {
        "processed": 0,
        "inserted": 0,
        "updated": 0,
        "skipped_no_doi": 0
    }

    try:
        with open(DUMP_PATH, 'r', encoding='utf-8-sig') as f: # utf-8-sig to handle BOM if any
            reader = csv.DictReader(f)
            
            # Prepare batch
            batch = []
            BATCH_SIZE = 1000
            
            for row in reader:
                stats["processed"] += 1
                
                raw_doi = row.get("DOI", "")
                if not raw_doi:
                    stats["skipped_no_doi"] += 1
                    continue
                
                doi = normalize_doi(raw_doi)
                title = row.get("Title", "")
                abstract = row.get("Abstract Note", "")
                year_str = row.get("Publication Year", "")
                year = int(year_str) if year_str and year_str.isdigit() else None
                venue = row.get("Publication Title", "") or row.get("Journal Abbreviation", "")
                url = row.get("Url", "")
                authors_json = parse_authors(row.get("Author", ""))
                
                now = datetime.utcnow().isoformat()
                
                # We use UPSERT strategy
                # If DOI exists, we update metadata but PRESERVE pdf_path if it wasn't null (excluded.pdf_path is null here effectively as we don't pass it)
                # Actually, in UPSERT, we specify what to update.
                
                batch.append((
                    title, abstract, authors_json, year, venue, doi, url, now, now, # Values for INSERT
                    title, abstract, authors_json, year, venue, url, now # Values for UPDATE
                ))
                
                if len(batch) >= BATCH_SIZE:
                    _execute_batch(cursor, batch, stats)
                    conn.commit()
                    batch = []
                    print(f"Processed {stats['processed']} records...", end='\r')
            
            if batch:
                _execute_batch(cursor, batch, stats)
                conn.commit()
                
    except Exception as e:
        logger.error(f"Error reading dump: {e}")
        conn.rollback()
    finally:
        conn.close()

    logger.info("\nIngestion Complete!")
    logger.info(f"Total Processed: {stats['processed']}")
    logger.info(f"Skipped (No DOI): {stats['skipped_no_doi']}")
    # Note: sqlite3 executemany doesn't easily return count of inserts vs updates without logic.
    # We just log total operations.

def _execute_batch(cursor, batch, stats):
    # UPSERT Syntax
    # INSERT INTO papers (...) VALUES (...) ON CONFLICT(doi) DO UPDATE SET ...
    
    sql = """
    INSERT INTO papers (title, abstract, authors, year, venue, doi, url, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(doi) DO UPDATE SET
        title = excluded.title,
        abstract = excluded.abstract,
        authors = excluded.authors,
        year = excluded.year,
        venue = excluded.venue,
        url = excluded.url,
        updated_at = excluded.updated_at
    """
    
    # batch items: (t, a, au, y, v, d, u, c, up, t, a, au, y, v, u, up) <- No, executemany takes parameters matching VALUES
    # The ON CONFLICT clause uses `excluded.` which refers to the values we tried to insert.
    # So we simply pass the VALUES parameters!
    
    # Tuple: (title, abstract, authors, year, venue, doi, url, created_at, updated_at)
    
    # Correction: pass only 9 args per row.
    
    clean_batch = [x[:9] for x in batch]
    
    try:
        cursor.executemany(sql, clean_batch)
    except sqlite3.Error as e:
        logger.error(f"Batch execution error: {e}")

if __name__ == "__main__":
    ingest_dump()
