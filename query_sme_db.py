import sqlite3
import json

db_path = "c:/gpt/SME/data/sme.db"
try:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get the latest 5 embedded papers
    cursor.execute("""
        SELECT doi, title, status, updated_at 
        FROM papers 
        WHERE status = 'embedded' 
        ORDER BY updated_at DESC 
        LIMIT 5
    """)
    rows = cursor.fetchall()
    
    results = [dict(row) for row in rows]
    print(json.dumps(results, indent=2))
    
    conn.close()
except Exception as e:
    print(f"Error: {e}")
