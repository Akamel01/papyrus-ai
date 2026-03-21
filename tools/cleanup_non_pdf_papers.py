import sqlite3
from pathlib import Path

DB_PATH = Path("sme.db")

def cleanup():
    if not DB_PATH.exists():
        print("sme.db not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("--- Database Cleanup (Legacy Scope Restoration) ---")
    
    # 1. Check Pre-Conditions
    cursor.execute("SELECT COUNT(*) FROM papers")
    total_before = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM papers WHERE pdf_path IS NOT NULL AND pdf_path != ''")
    with_pdf = cursor.fetchone()[0]
    
    to_delete_count = total_before - with_pdf
    
    if to_delete_count > 0:
        print(f"Total Papers: {total_before}")
        print(f"Papers with PDF (Keep): {with_pdf}")
        print(f"Papers without PDF (Delete): {to_delete_count}")
        
        # 2. Delete
        print("Deleting records without PDF path...")
        cursor.execute("DELETE FROM papers WHERE pdf_path IS NULL OR pdf_path = ''")
        conn.commit()
        
        # 3. Verify
        cursor.execute("SELECT COUNT(*) FROM papers")
        total_after = cursor.fetchone()[0]
        print(f"Cleanup Complete. Total Papers: {total_after}")
        
        if total_after == with_pdf:
            print("SUCCESS: Database now contains only papers with PDF paths.")
        else:
            print(f"WARNING: Discrepancy detected. Expected {with_pdf}, got {total_after}")
            
    else:
        print("No non-PDF papers found. Database is already clean.")
        
    conn.close()

if __name__ == "__main__":
    cleanup()
