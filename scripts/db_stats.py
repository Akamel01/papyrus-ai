
import sqlite3
import pandas as pd
from pathlib import Path

def inspect_db():
    db_path = Path("data/sme.db")
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return

    try:
        conn = sqlite3.connect(db_path)
        
        print("\n=== PAPERS BY SOURCE ===")
        df_source = pd.read_sql_query("SELECT source, COUNT(*) as count FROM papers GROUP BY source ORDER BY count DESC", conn)
        print(df_source.to_markdown(index=False))

        print("\n=== PAPERS BY STATUS ===")
        df_status = pd.read_sql_query("SELECT status, COUNT(*) as count FROM papers GROUP BY status ORDER BY count DESC", conn)
        print(df_status.to_markdown(index=False))
        
        print("\n=== TOTAL PAPERS ===")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM papers")
        print(f"Total: {cursor.fetchone()[0]}")
        
    except Exception as e:
        print(f"Error inspecting DB: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    inspect_db()
