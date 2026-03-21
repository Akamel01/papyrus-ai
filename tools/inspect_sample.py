"""Inspect sample of complete and incomplete records in sme.db"""
import sqlite3
import json
import random

conn = sqlite3.connect('data/sme.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("=== SAMPLE: COMPLETE RECORDS (APA Ready) ===")
c.execute("""
    SELECT doi, title, authors, year, venue 
    FROM papers 
    WHERE authors IS NOT NULL AND authors != '' AND authors != '[]' AND authors != 'null'
    AND year IS NOT NULL
    LIMIT 50
""")
rows = c.fetchall()
if rows:
    sample = random.sample(rows, min(5, len(rows)))
    for r in sample:
        authors = json.loads(r['authors'])
        author_str = f"{len(authors)} authors" if isinstance(authors, list) else "Invalid JSON"
        print(f"DOI: {r['doi']}")
        print(f"Title: {r['title'][:60]}...")
        print(f"Year: {r['year']} | Venue: {r['venue']}")
        print(f"Authors: {author_str} ({authors[:2] if isinstance(authors, list) else ''}...)")
        print("-" * 40)
else:
    print("No complete records found!")

print("\n=== SAMPLE: INCOMPLETE RECORDS (Failed Resolution) ===")
c.execute("""
    SELECT doi, title, authors, year 
    FROM papers 
    WHERE (authors IS NULL OR authors = '' OR authors = '[]' OR authors = 'null' OR year IS NULL)
    AND doi IS NOT NULL
    LIMIT 50
""")
rows = c.fetchall()
if rows:
    sample = random.sample(rows, min(5, len(rows)))
    for r in sample:
        print(f"DOI: {r['doi']}")
        print(f"Title: {r['title']}")
        print(f"Missing: {'Authors' if not r['authors'] or r['authors']=='[]' else ''} {'Year' if not r['year'] else ''}")
        print("-" * 40)

conn.close()
