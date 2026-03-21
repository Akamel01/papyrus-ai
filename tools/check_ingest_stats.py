import sqlite3
from pathlib import Path

DB_PATH = Path("sme.db")

def check_stats():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM papers")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM papers WHERE authors IS NOT NULL AND authors != '[]' AND authors != ''")
    with_authors = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM papers WHERE year IS NOT NULL")
    with_year = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM papers WHERE venue IS NOT NULL AND venue != ''")
    with_venue = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM papers WHERE updated_at > datetime('now', '-5 minutes')")
    recently_updated = cursor.fetchone()[0]
    
    print(f"Total Papers: {total}")
    print(f"With Authors: {with_authors} ({(with_authors/total)*100:.1f}%)")
    print(f"With Year:    {with_year} ({(with_year/total)*100:.1f}%)")
    print(f"With Venue:   {with_venue} ({(with_venue/total)*100:.1f}%)")
    print(f"Recently Updated (Ingested): {recently_updated}")
    
    conn.close()

if __name__ == "__main__":
    check_stats()
