import sqlite3
import json
from pathlib import Path

DB_PATH = Path("data/sme.db")
PAPERS_DIR = Path("DataBase/Papers")

def prune_and_report():
    if not DB_PATH.exists():
        print(f"{DB_PATH} not found.")
        return

    print(f"--- Pruning Database to Legacy Scope ---")
    
    # 1. Load Allowlist (Filesystem)
    allowed_files = set()
    for f in PAPERS_DIR.glob("*.pdf"):
        allowed_files.add(f.name)
        
    print(f"Legacy Corpus: {len(allowed_files)} PDF files.")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 2. Scan DB
    cursor.execute("SELECT id, pdf_path FROM papers")
    rows = cursor.fetchall()
    
    to_delete_ids = []
    kept_count = 0
    
    for r in rows:
        path = r['pdf_path']
        if not path:
            to_delete_ids.append(r['id'])
            continue
            
        filename = Path(path).name
        if filename in allowed_files:
            kept_count += 1
        else:
            to_delete_ids.append(r['id'])
            
    print(f"Database Records: {len(rows)}")
    print(f"Surplus/Ghost Records to Delete: {len(to_delete_ids)}")
    print(f"Records to Keep: {kept_count}")
    
    # 3. Delete
    if to_delete_ids:
        print("Deleting surplus records...")
        # Split into batches to avoid SQL limits
        BATCH_SIZE = 900
        for i in range(0, len(to_delete_ids), BATCH_SIZE):
            batch = to_delete_ids[i:i+BATCH_SIZE]
            placeholders = ','.join('?' for _ in batch)
            cursor.execute(f"DELETE FROM papers WHERE id IN ({placeholders})", batch)
        conn.commit()
        print("Pruning Complete.")
    else:
        print("Database is already compliant.")
        
    # 4. Report Metadata Gaps on Remaining Papers
    print("\n--- Final Metadata Audit (Strict 52,630 Scope) ---")
    cursor.execute("SELECT * FROM papers")
    final_rows = cursor.fetchall()
    
    missing_metadata_count = 0
    missing_examples = []
    
    for r in final_rows:
        # Check basic fields: Title, Authors, Year, Venue, DOI
        # (Gap definition: Any of these missing)
        
        has_title = bool(r['title'])
        has_year = bool(r['year'])
        has_venue = bool(r['venue'])
        has_doi = bool(r['doi'])
        
        has_authors = False
        try:
            auths = json.loads(r['authors'])
            if isinstance(auths, list) and len(auths) > 0:
                has_authors = True
        except:
            pass
            
        if not (has_title and has_year and has_venue and has_doi and has_authors):
            missing_metadata_count += 1
            if len(missing_examples) < 3:
                missing_examples.append(Path(r['pdf_path']).name)

    print(f"Total Papers: {len(final_rows)}")
    print(f"Papers Missing Metadata: {missing_metadata_count}")
    percentage = (missing_metadata_count / len(final_rows)) * 100
    print(f"Deficit: {percentage:.1f}%")
    
    if missing_examples:
        print(f"Examples of missing metadata: {', '.join(missing_examples)}")

    conn.close()

if __name__ == "__main__":
    prune_and_report()
