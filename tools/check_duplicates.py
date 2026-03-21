import sqlite3
from pathlib import Path

DB_PATH = Path("sme.db")

def check_duplicates():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("--- Database Deduplication Check ---")
    
    # 1. Check Schema for Unique Constraint
    cursor.execute("PRAGMA index_list(papers)")
    indexes = cursor.fetchall()
    print(f"Indexes on papers: {indexes}")
    
    # 2. Check for DOI duplicates (case insensitive)
    print("\nChecking for DOI duplicates...")
    cursor.execute("""
        SELECT lower(doi), count(*) 
        FROM papers 
        WHERE doi IS NOT NULL AND doi != '' 
        GROUP BY lower(doi) 
        HAVING count(*) > 1
    """)
    doi_dupes = cursor.fetchall()
    if doi_dupes:
        print(f"Found {len(doi_dupes)} DOIs with duplicates.")
        print(f"Sample: {doi_dupes[:5]}")
    else:
        print("No exact DOI duplicates found (case-insensitive).")

    # 3. Check for Title duplicates (exact match)
    print("\nChecking for Title duplicates...")
    cursor.execute("""
        SELECT title, count(*) 
        FROM papers 
        WHERE title IS NOT NULL AND title != '' 
        GROUP BY title 
        HAVING count(*) > 1
    """)
    title_dupes = cursor.fetchall()
    if title_dupes:
        print(f"Found {len(title_dupes)} Titles with duplicates.")
        print(f"Sample: {title_dupes[:5]}")
    else:
        print("No Title duplicates found.")
        
    conn.close()

if __name__ == "__main__":
    check_duplicates()
