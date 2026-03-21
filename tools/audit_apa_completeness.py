import sqlite3
import json
from pathlib import Path

# Config
DB_PATH = Path("data/sme.db")
PAPERS_DIR = Path("DataBase/Papers")

def audit_completeness():
    print(f"--- APA Completeness Audit ---")
    print(f"Database: {DB_PATH}")
    print(f"Papers Dir: {PAPERS_DIR}")

    if not DB_PATH.exists():
        print("CRITICAL: Database not found!")
        return

    # 1. Scan PDFs (Ground Truth)
    pdf_files = list(PAPERS_DIR.glob("*.pdf"))
    pdf_names = {p.name: p for p in pdf_files}
    print(f"\n[1] Legacy Corpus (Filesystem)")
    print(f"    Found {len(pdf_files)} PDF files.")

    # 2. Scan Database
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all papers
    cursor.execute("SELECT * FROM papers")
    db_rows = cursor.fetchall()
    print(f"\n[2] Database Records")
    print(f"    Found {len(db_rows)} records.")
    
    # 3. Correlation & Completeness
    
    # Map DB records by filename (assuming pdf_path contains filename)
    # Handle absolute/relative paths
    db_map = {}
    for r in db_rows:
        path = r['pdf_path']
        if path:
            name = Path(path).name
            db_map[name] = r
            
    # Metrics
    missing_in_db = []
    incomplete_apa = []
    missing_vol_issue = 0 # Tracking specifically
    
    print("\n[3] Auditing Metadata...")
    
    for name, pdf_path in pdf_names.items():
        if name not in db_map:
            missing_in_db.append(name)
            continue
            
        row = db_map[name]
        
        # Check Fields
        issues = []
        
        # Title
        if not row['title']: issues.append("Missing Title")
        
        # Authors (Must be valid JSON list with at least 1 author)
        authors_ok = False
        try:
            auths = json.loads(row['authors'])
            if isinstance(auths, list) and len(auths) > 0:
                authors_ok = True
        except:
            pass
        if not authors_ok: issues.append("Missing/Invalid Authors")
            
        # Year
        if not row['year']: issues.append("Missing Year")
        
        # Venue (Journal)
        if not row['venue']: issues.append("Missing Venue")
        
        # DOI
        if not row['doi']: issues.append("Missing DOI")
        
        # Volume/Issue/Pages
        # Check if columns exist (using verify_db output knowledge: they DON'T)
        # But let's check keys just in case dictionaried row has them?
        keys = row.keys()
        if 'volume' not in keys and 'metadata' not in keys:
            missing_vol_issue += 1
            # We treat this as a systemic issue for now, usually fatal for APA
            # issues.append("Missing Vol/Issue/Pages (Schema Limit)")
            
        elif 'metadata' in keys:
             # Check inside metadata
             try:
                 md = json.loads(row['metadata'])
                 if not md.get('volume') and not md.get('issue') and not md.get('pages'):
                     missing_vol_issue += 1
             except:
                 missing_vol_issue += 1
                 
        if issues:
            incomplete_apa.append((name, issues))

    # Report
    print(f"\n[4] Findings")
    
    if missing_in_db:
        print(f"  CRITICAL: {len(missing_in_db)} PDFs are NOT in the database.")
        print(f"  Example: {missing_in_db[0]}")
    else:
        print(f"  SUCCESS: All {len(pdf_files)} PDFs have a corresponding DB record.")
        
    print(f"  APA Completeness:")
    if incomplete_apa:
        print(f"    {len(incomplete_apa)} papers have missing basic fields (Title, Author, Year, Venue).")
        print(f"    Example: {incomplete_apa[0]}")
    else:
        print(f"    SUCCESS: All papers have basic APA fields (Title, Author, Year, Venue).")
        
    print(f"  Volume/Issue/Pages Check:")
    if missing_vol_issue > 0:
        print(f"    WARNING: {missing_vol_issue} papers are missing Volume/Issue/Pages information.")
        print(f"    (Likely due to schema limitation - these columns do not exist).")
    else:
        print(f"    SUCCESS: Volume/Issue/Pages info found.")

    conn.close()

if __name__ == "__main__":
    audit_completeness()
