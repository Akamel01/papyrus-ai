import sqlite3
from pathlib import Path

def check(path_str):
    p = Path(path_str)
    print(f"Checking {p}...")
    if not p.exists():
        print(f"  MISSING")
        return
    
    try:
        conn = sqlite3.connect(p)
        cursor = conn.cursor()
        
        # Schema
        cursor.execute("PRAGMA table_info(papers)")
        rows = cursor.fetchall()
        cols = [r[1] for r in rows]
        print(f"  Columns: {cols}")
        
        # Count
        try:
            cursor.execute("SELECT COUNT(*) FROM papers")
            cnt = cursor.fetchone()[0]
            print(f"  Rows: {cnt}")
        except:
            print("  Table 'papers' missing or error.")
        
        # PDF Count
        if 'pdf_path' in cols:
            cursor.execute("SELECT COUNT(*) FROM papers WHERE pdf_path IS NOT NULL AND pdf_path != ''")
            pdf_cnt = cursor.fetchone()[0]
            print(f"  PDFs: {pdf_cnt}")
            
    except Exception as e:
        print(f"  Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    check("sme.db")
    check("data/sme.db")
