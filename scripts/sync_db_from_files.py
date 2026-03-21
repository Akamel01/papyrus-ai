import sys
import os
import sqlite3
import logging
import json
from pathlib import Path
from datetime import datetime
import re

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage import DatabaseManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def normalize_unique_id(filename: str) -> dict:
    """
    Mirror the ID generation logic from PaperDiscoverer._get_existing_paper_ids
    and DiscoveredPaper.unique_id to ensure consistency.
    """
    stem = filename.replace(".pdf", "")
    
    # 1. ArXiv Pattern (Matches PaperDiscoverer logic)
    # Pattern: explicit "arXiv-" prefix often used in file naming
    if stem.lower().startswith("arxiv-"):
        arxiv_id = stem[6:] # Strip "arXiv-"
        return {
            "unique_id": f"arxiv:{arxiv_id.lower()}",
            "doi": None,
            "arxiv_id": arxiv_id,
            "source": "arxiv",
            "title": stem # Fallback title
        }
        
    # 2. ArXiv Pattern (Raw ID like 2101.12345)
    # PaperDiscoverer doesn't strictly handle this in filesystem scan, 
    # but we should be robust.
    if re.match(r'^\d{4}\.\d{4,5}(v\d+)?$', stem):
        return {
            "unique_id": f"arxiv:{stem.lower()}",
            "doi": None,
            "arxiv_id": stem,
            "source": "arxiv",
            "title": stem
        }

    # 3. DOI Pattern
    # PaperDiscoverer assumes filenames with underscores are DOIs
    # logic: doi = filename.replace("_", "/")
    # unique_id = f"doi:{doi.lower()}"
    
    # We apply this if it looks like a DOI (starts with 10.)
    if stem.startswith("10."):
        doi = stem.replace("_", "/")
        return {
            "unique_id": f"doi:{doi.lower()}",
            "doi": doi,
            "arxiv_id": None,
            "source": "doi",
            "title": stem
        }

    # 4. Fallback (Title)
    # If it's just a title string
    normalized_title = stem.lower()
    normalized_title = re.sub(r'[^\w\s]', '', normalized_title)
    normalized_title = ' '.join(normalized_title.split())
    
    return {
        "unique_id": f"title:{normalized_title}",
        "doi": None,
        "arxiv_id": None,
        "source": "manual_import",
        "title": stem
    }

def main():
    papers_dir = Path("DataBase/Papers")
    db_path = Path("data/sme.db")
    
    if not papers_dir.exists():
        logger.error(f"Paper directory not found: {papers_dir}")
        return

    logger.info(f"Syncing DB {db_path} from files in {papers_dir}...")
    
    # Initialize DB (creates schema if missing)
    db_manager = DatabaseManager(str(db_path))
    
    # Get all files
    pdf_files = list(papers_dir.glob("*.pdf"))
    logger.info(f"Scanning {len(pdf_files)} PDFs...")
    
    imported = 0
    skipped = 0
    
    with db_manager.get_connection() as conn:
        for pdf in pdf_files:
            try:
                meta = normalize_unique_id(pdf.name)
                
                # Check duplication first to avoid unique constraint errors flooding logs
                exists = conn.execute(
                    "SELECT 1 FROM papers WHERE unique_id = ?", 
                    (meta['unique_id'],)
                ).fetchone()
                
                if exists:
                    skipped += 1
                    continue

                # Insert with status='embedded' so the pipeline ignores it
                # but valid for RAG/Monitoring
                conn.execute("""
                    INSERT INTO papers (
                        unique_id, 
                        doi, 
                        arxiv_id, 
                        title, 
                        source, 
                        pdf_path, 
                        status, 
                        created_at, 
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (
                    meta["unique_id"],
                    meta["doi"],
                    meta["arxiv_id"],
                    meta["title"],
                    meta["source"],
                    str(pdf),
                    "embedded"  # <--- CRITICAL: Prevents re-processing
                ))
                imported += 1
                
            except Exception as e:
                logger.error(f"Error processing {pdf.name}: {e}")
            
            if imported > 0 and imported % 1000 == 0:
                logger.info(f"Imported {imported}...")
                conn.commit()

    logger.info(f"✅ Sync Complete.")
    logger.info(f"   Imported: {imported}")
    logger.info(f"   Skipped (Already in DB): {skipped}")
    logger.info(f"   Total Files Scanned: {len(pdf_files)}")

if __name__ == "__main__":
    main()
