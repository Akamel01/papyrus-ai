import sqlite3
from pathlib import Path

DB_PATH = Path("sme.db")

def check_status():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("--- Status Distribution ---")
    cursor.execute("SELECT status, count(*) FROM papers GROUP BY status")
    rows = cursor.fetchall()
    for r in rows:
        print(r)
        
    print("\n--- PDF Path Analysis ---")
    cursor.execute("SELECT count(*) FROM papers WHERE pdf_path IS NULL OR pdf_path = ''")
    null_pdf = cursor.fetchone()[0]
    print(f"Papers with NULL/Empty pdf_path: {null_pdf}")
    
    cursor.execute("SELECT count(*) FROM papers WHERE pdf_path IS NOT NULL AND pdf_path != ''")
    valid_pdf = cursor.fetchone()[0]
    print(f"Papers with valid pdf_path: {valid_pdf}")
    
    conn.close()

if __name__ == "__main__":
    check_status()
