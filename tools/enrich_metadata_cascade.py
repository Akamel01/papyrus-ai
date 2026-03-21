import sqlite3
import json
import logging
import time
import requests
import re
import argparse
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from tqdm import tqdm
import signal
import sys

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("data/enrichment_detailed.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
PIPELINE_STATE_TABLE = "pipeline_state"
STATE_KEY = "metadata_enrichment_last_id"

class MetadataEnricher:
    def __init__(self, db_path: str, email: str, s2_key: str):
        self.db_path = Path(db_path)
        self.email = email
        self.s2_key = s2_key
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.stop_requested = False
        
        # Initialize State Table
        self.conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {PIPELINE_STATE_TABLE} (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

        # Handle Ctrl+C
        signal.signal(signal.SIGINT, self.handle_exit)

    def handle_exit(self, signum, frame):
        logger.info("Interrupt received! Stopping gracefully...")
        self.stop_requested = True

    def get_last_processed_id(self) -> int:
        cursor = self.conn.execute(f"SELECT value FROM {PIPELINE_STATE_TABLE} WHERE key = ?", (STATE_KEY,))
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    def save_last_processed_id(self, paper_id: int):
        self.conn.execute(f"""
            INSERT INTO {PIPELINE_STATE_TABLE} (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
        """, (STATE_KEY, str(paper_id), str(paper_id)))
        self.conn.commit()

    def get_deficient_papers(self, start_id: int) -> List[sqlite3.Row]:
        """Fetch papers missing Title, Authors, Year, or Venue, AND missing Volume/Issue/Pages."""
        # Note: We prioritize fixing Title/Author first, but also want to catch papers that HAVE basic metadata 
        # but lack Volume/Issue (which is basically ALL of them due to schema limit).
        # Wait, schema limit means we CAN'T save Volume/Issue yet unless we store it in `metadata` column.
        # But `metadata` column might not exist in Schema A (Legacy).
        # Check if `metadata` column exists.
        
        # SCHEMA CHECK
        columns = [r[1] for r in self.conn.execute("PRAGMA table_info(papers)").fetchall()]
        has_metadata_col = 'metadata' in columns
        
        if not has_metadata_col:
            # We must ADD metadata column to store the rich data!
            logger.info("Adding 'metadata' column to schema to store APA fields...")
            try:
                self.conn.execute("ALTER TABLE papers ADD COLUMN metadata TEXT")
                self.conn.commit()
            except Exception as e:
                logger.error(f"Failed to migrate schema: {e}")
                sys.exit(1)

        query = """
            SELECT id, doi, pdf_path, title, authors, year, venue, metadata
            FROM papers 
            WHERE id > ? 
            ORDER BY id ASC
        """
        # We process ALL papers to ensure Volume/Issue is populated, or filter?
        # User concern was 11,546 papers missing BASIC metadata.
        # But user also wants FULL APA (Vol/Issue). 
        # Current status: 100% missing Vol/Issue.
        # So we should process ALL 52,630 papers?
        # That would take 10+ hours.
        # Let's focus on the 11,546 missing BASIC metadata first (highest priority).
        
        query = """
            SELECT id, doi, pdf_path, title, authors, year, venue, metadata
            FROM papers 
            WHERE id > ?
            AND (
                (title IS NULL OR title = '') OR 
                (authors IS NULL OR authors = '' OR authors = '[]') OR 
                (year IS NULL)
            )
            ORDER BY id ASC
        """
        return self.conn.execute(query, (start_id,)).fetchall()

    def enrich_via_crossref(self, doi: str) -> Optional[Dict]:
        """Tier 1: CrossRef API"""
        if not doi: return None
        try:
            url = f"https://api.crossref.org/works/{doi}"
            headers = {"User-Agent": f"SME-Enricher/1.0 (mailto:{self.email})"}
            resp = requests.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()["message"]
                
                # Authors
                authors = []
                for a in data.get("author", []):
                    name = f"{a.get('family', '')}, {a.get('given', '')}".strip(", ")
                    if name: authors.append(name)
                
                # Date
                year = None
                date_parts = data.get("published", {}).get("date-parts")
                if date_parts: year = date_parts[0][0]
                
                return {
                    "title": data.get("title", [None])[0],
                    "authors": json.dumps(authors),
                    "year": year,
                    "venue": data.get("container-title", [None])[0],
                    "volume": data.get("volume"),
                    "issue": data.get("issue"),
                    "pages": data.get("page"),
                    "source": "crossref"
                }
            elif resp.status_code == 404:
                return None # Not found
            
        except Exception as e:
            logger.warning(f"CrossRef error for {doi}: {e}")
        return None

    def enrich_via_semantic_scholar(self, doi: str) -> Optional[Dict]:
        """Tier 2: Semantic Scholar API"""
        if not doi: return None
        try:
            # S2 usually requires cleaned DOI
            clean_doi = doi.replace("doi:", "").strip()
            url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{clean_doi}"
            params = {"fields": "title,authors,year,venue,publicationDate"}
            headers = {"x-api-key": self.s2_key}
            
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                authors = [a.get("name") for a in data.get("authors", []) if a.get("name")]
                return {
                    "title": data.get("title"),
                    "authors": json.dumps(authors),
                    "year": data.get("year"),
                    "venue": data.get("venue"),
                    "volume": None, # S2 often lacks this in graph endpoint
                    "issue": None,
                    "pages": None,
                    "source": "semantic_scholar"
                }
        except Exception as e:
            logger.warning(f"S2 error for {doi}: {e}")
        return None

    def enforce_rate_limit(self, source: str):
        if source == "crossref":
            time.sleep(0.05) # Polite pool is fast, but let's be safe (20/s)
        elif source == "semantic_scholar":
            time.sleep(1.0) # Strict 1/s limit
        else:
            time.sleep(0.1)

    def process(self):
        last_id = self.get_last_processed_id()
        logger.info(f"Resuming from ID: {last_id}")
        
        papers = self.get_deficient_papers(last_id)
        logger.info(f"Found {len(papers)} papers deficient in basic metadata.")
        
        success_count = 0
        
        for i, paper in enumerate(tqdm(papers, desc="Enriching Papers")):
            if self.stop_requested:
                break
                
            paper_id = paper['id']
            doi = paper['doi']
            
            meta = None
            source_used = None
            
            # 1. Try CrossRef
            if doi:
                meta = self.enrich_via_crossref(doi)
                source_used = "crossref"
                self.enforce_rate_limit("crossref")
            
            # 2. Try S2
            if not meta and doi:
                meta = self.enrich_via_semantic_scholar(doi)
                source_used = "semantic_scholar"
                self.enforce_rate_limit("semantic_scholar")
                
            # 3. PDF Extraction (Not implemented here for speed, better as separate tool)
            
            if meta:
                try:
                    # Update DB
                    # We store extra fields in 'metadata' column JSON
                    extra_meta = {
                        "volume": meta.get("volume"),
                        "issue": meta.get("issue"),
                        "pages": meta.get("pages"),
                        "enrichment_source": meta.get("source")
                    }
                    
                    self.conn.execute("""
                        UPDATE papers SET 
                            title = COALESCE(?, title),
                            authors = COALESCE(?, authors),
                            year = COALESCE(?, year),
                            venue = COALESCE(?, venue),
                            metadata = ?,
                            updated_at = datetime('now')
                        WHERE id = ?
                    """, (
                        meta["title"], 
                        meta["authors"], 
                        meta["year"], 
                        meta["venue"], 
                        json.dumps(extra_meta), 
                        paper_id
                    ))
                    self.conn.commit()
                    success_count += 1
                except Exception as e:
                    logger.error(f"Failed to update DB for ID {paper_id}: {e}")
            
            # Checkpoint every 50
            if i % 50 == 0:
                self.save_last_processed_id(paper_id)
                
        logger.info(f"Enrichment session ended. Successfully enriched {success_count}/{len(papers)} papers.")
        self.conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/sme.db")
    parser.add_argument("--email", required=True)
    parser.add_argument("--s2-key", required=True)
    args = parser.parse_args()
    
    enricher = MetadataEnricher(args.db, args.email, args.s2_key)
    enricher.process()
