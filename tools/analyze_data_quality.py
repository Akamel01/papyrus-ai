import sqlite3
import re
import json
from pathlib import Path

# Corrected PDF path
DB_PATH = Path("data/sme.db")

def is_valid_doi(doi):
    if not doi:
        return False
    pattern = r'^10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+'
    return bool(re.match(pattern, doi))

def analyze_quality():
    if not DB_PATH.exists():
        print(f"{DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print(f"--- Data Quality Audit ({DB_PATH}) ---")
    
    cursor.execute("SELECT * FROM papers")
    
    stats = {
        "total": 0,
        "valid_json_authors": 0,
        "valid_year": 0,
        "valid_venue": 0,
        "has_abstract": 0
    }
    
    for row in cursor:
        stats["total"] += 1
        
        # Authors
        authors = row['authors']
        try:
            parsed = json.loads(authors) if authors else []
            if isinstance(parsed, list) and len(parsed) > 0:
                stats["valid_json_authors"] += 1
        except:
            pass
            
        # Year
        if row['year'] and isinstance(row['year'], int):
            stats["valid_year"] += 1
            
        # Venue
        if row['venue']:
            stats["valid_venue"] += 1
            
        # Abstract
        if row['abstract']:
            stats["has_abstract"] += 1

    print(f"\nTotal Records: {stats['total']}")
    print(f"Enriched Stats:")
    print(f"  Valid Authors: {stats['valid_json_authors']} ({stats['valid_json_authors']/stats['total']*100:.1f}%)")
    print(f"  Valid Year:    {stats['valid_year']} ({stats['valid_year']/stats['total']*100:.1f}%)")
    print(f"  Valid Venue:   {stats['valid_venue']} ({stats['valid_venue']/stats['total']*100:.1f}%)")
    print(f"  Has Abstract:  {stats['has_abstract']} ({stats['has_abstract']/stats['total']*100:.1f}%)")
    
    conn.close()

if __name__ == "__main__":
    analyze_quality()
