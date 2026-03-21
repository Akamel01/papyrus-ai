#!/usr/bin/env python
"""
Migration tool to populate SQLite database from existing JSON files.
Preserves existing data while transitioning to the new storage backend.
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.storage import DatabaseManager, PaperStore, StateStore
from src.acquisition.paper_discoverer import DiscoveredPaper

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "sme.db"
DISCOVERY_CACHE = DATA_DIR / "discovery_cache.json"
UPDATED_PAPERS_DIR = Path("DataBase/UpdatedPapers") # Note case sensitivity
PIPELINE_HISTORY = DATA_DIR / "pipeline_history.jsonl"

def migrate_discovery_cache(store: PaperStore):
    """Migrate discovered papers from cache JSON."""
    if not DISCOVERY_CACHE.exists():
        logger.warning("No discovery cache found to migrate.")
        return

    logger.info(f"Loading discovery cache: {DISCOVERY_CACHE}")
    try:
        with open(DISCOVERY_CACHE, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
            raw_papers = cache_data.get("papers", [])
            
        count = 0
        skipped = 0
        for p_dict in raw_papers:
            # Convert dictionary to DiscoveredPaper object
            # Handle potential field discrepancies
            try:
                paper = DiscoveredPaper(
                    doi=p_dict.get('doi'),
                    arxiv_id=p_dict.get('arxiv_id'),
                    openalex_id=p_dict.get('openalex_id'),
                    title=p_dict.get('title', ''),
                    authors=p_dict.get('authors', []),
                    year=p_dict.get('year'),
                    venue=p_dict.get('venue'),
                    abstract=p_dict.get('abstract'),
                    pdf_url=p_dict.get('pdf_url'),
                    status=p_dict.get('status','discovered'), 
                    source=p_dict.get('source', '')
                )
                
                # If it already exists, skipping is fine (or update?)
                # We'll try to add, if exists it returns False
                if store.add_paper(paper):
                    count += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.error(f"Failed to migrate paper entry: {e}")

        logger.info(f"Discovery migration complete. Added: {count}, Skipped (Duplicate): {skipped}")
        
    except Exception as e:
        logger.error(f"Failed to read discovery cache: {e}")

def migrate_downloaded_papers(store: PaperStore):
    """Migrate manually downloaded papers (overwrites status)."""
    if not UPDATED_PAPERS_DIR.exists():
        logger.warning("No UpdatedPapers directory found.")
        return

    json_files = list(UPDATED_PAPERS_DIR.glob("*.json"))
    logger.info(f"Found {len(json_files)} metadata files in {UPDATED_PAPERS_DIR}")
    
    updated_count = 0
    
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                p_dict = json.load(f)
                
            # These papers are at least downloaded
            # We construct a DiscoveredPaper to ensure we have identifiers
            paper = DiscoveredPaper(
                doi=p_dict.get('doi'),
                arxiv_id=p_dict.get('arxiv_id'),
                openalex_id=p_dict.get('openalex_id'),
                title=p_dict.get('title', ''),
                authors=p_dict.get('authors', []),
                year=p_dict.get('year'),
                venue=p_dict.get('venue'),
                abstract=p_dict.get('abstract'),
                pdf_url=p_dict.get('pdf_url'),
                status='downloaded',
                pdf_path=p_dict.get('pdf_path'),
                source=p_dict.get('source', '')
            )
            
            # Identify by unique_id logic (reused from class)
            unique_id = paper.unique_id
            
            # Check if exists to update, or add new
            if store.status_exists(unique_id):
                store.update_status(unique_id, 'downloaded', pdf_path=paper.pdf_path)
                updated_count += 1
            else:
                store.add_paper(paper) # Will set status='downloaded' from object
                updated_count += 1
                
        except Exception as e:
            logger.error(f"Failed to migrate metadata {json_file}: {e}")
            
    logger.info(f"Downloaded metadata migration complete. Processed: {updated_count}")

def main():
    logger.info("Starting SQLite Migration...")
    
    # Initialize DB (creates file and schema)
    db = DatabaseManager(DB_PATH)
    paper_store = PaperStore(db)
    state_store = StateStore(db)
    
    # 1. Migrate Discovery Cache
    migrate_discovery_cache(paper_store)
    
    # 2. Migrate Downloaded Papers (updates status)
    migrate_downloaded_papers(paper_store)
    
    logger.info("✅ Migration finished successfully.")
    logger.info(f"Database location: {DB_PATH.absolute()}")

if __name__ == "__main__":
    main()
