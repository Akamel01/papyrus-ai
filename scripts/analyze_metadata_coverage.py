import sqlite3
import json
import logging
from pathlib import Path

# Setup simple logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("analyzer")

DB_PATH = "data/sme.db"

def analyze_coverage():
    db_file = Path("c:/gpt/SME/data/sme.db")
    if not db_file.exists():
        print(f"Database not found at {db_file}")
        return

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get total count
    cursor.execute("SELECT COUNT(*) FROM papers")
    first_row = cursor.fetchone()
    total_papers = first_row[0]
    
    if total_papers == 0:
        print("Database is empty.")
        conn.close()
        return

    print(f"Analyzing {total_papers} papers in {db_file}...\n")

    # Metrics counters
    missing_counts = {
        "title": 0,
        "authors": 0,
        "year": 0,
        "venue": 0,
        "doi": 0,
        "apa_reference": 0, # NEW: Check APA column
        "volume": 0,
        "issue": 0,
        "pages": 0,
        "abstract": 0
    }

    # Iterate efficiently
    cursor.execute("SELECT title, authors, year, venue, doi, apa_reference, abstract, metadata FROM papers")
    
    processed_count = 0
    for row in cursor:
        processed_count += 1
        
        # Check Top-Level Fields
        # Title
        title_val = row["title"]
        if not title_val or title_val == "Unknown Title" or title_val.strip() == "":
            missing_counts["title"] += 1
            
        # Authors (JSON list or string)
        auths_val = row["authors"]
        if not auths_val or auths_val == '[]' or auths_val == 'null':
             missing_counts["authors"] += 1
        
        # Year
        year_val = row["year"]
        if not year_val:
            missing_counts["year"] += 1
            
        # Venue
        venue_val = row["venue"]
        if not venue_val:
             missing_counts["venue"] += 1
             
        # DOI
        doi_val = row["doi"]
        if not doi_val:
             missing_counts["doi"] += 1

        # APA Reference (Column)
        apa_val = row["apa_reference"]
        if not apa_val:
            missing_counts["apa_reference"] += 1

        # Abstract
        abs_val = row["abstract"]
        if not abs_val:
            missing_counts["abstract"] += 1

        # Check Nested Fields
        # 1. Safely extract metadata dict
        meta_val = row["metadata"]
        meta = {}
        if meta_val:
            if isinstance(meta_val, str):
                try:
                    meta = json.loads(meta_val)
                except:
                    meta = {} # Malformed JSON
            elif isinstance(meta_val, dict):
                 meta = meta_val
        
        # 2. Check keys
        if not meta.get("volume"): missing_counts["volume"] += 1
        if not meta.get("issue"): missing_counts["issue"] += 1
        
        # Pages logic (first_page, last_page, or pages)
        has_pages = False
        if meta.get("pages") or meta.get("first_page") or meta.get("last_page"):
            has_pages = True
        if not has_pages: 
            missing_counts["pages"] += 1

    conn.close()

    # Report
    print("=== METADATA COVERAGE REPORT ===")
    print(f"{'FIELD':<20} | {'MISSING %':<10} | {'COUNT':<10}")
    print("-" * 50)
    
    for field, count in missing_counts.items():
        percent = (count / total_papers) * 100
        print(f"{field:<20} | {percent:<6.1f}%    | {count}")

if __name__ == "__main__":
    analyze_coverage()
