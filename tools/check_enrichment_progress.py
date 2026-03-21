import sqlite3
from pathlib import Path

# DB Path
DB_PATH = Path("data/sme.db")

def check_progress():
    if not DB_PATH.exists():
        print(f"{DB_PATH} missing.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print(f"--- Enrichment Progress Check ({DB_PATH}) ---")
    
    # Check updated_at timestamps
    # Look for updates in the last 25 minutes
    try:
        cursor.execute("SELECT COUNT(*) FROM papers WHERE updated_at > datetime('now', '-25 minutes')")
        recent = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM papers")
        total = cursor.fetchone()[0]
        
        print(f"Total Papers: {total}")
        print(f"Recently Updated (Last 25m): {recent}")
        
        if recent > 0:
            print("STATUS: Data is being actively updated.")
        else:
            print("STATUS: No recent updates found. Script might be stuck or finished.")
            
        # Check Abstract Count
        cursor.execute("SELECT COUNT(*) FROM papers WHERE abstract IS NOT NULL AND length(abstract) > 50")
        abstracts = cursor.fetchone()[0]
        print(f"Papers with Abstracts: {abstracts}")
        
    except Exception as e:
        print(f"Error: {e}")
        
    conn.close()

if __name__ == "__main__":
    check_progress()
