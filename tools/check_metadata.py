"""Check metadata completeness in sme.db"""
import sqlite3

conn = sqlite3.connect('data/sme.db')
c = conn.cursor()

# Total count
c.execute('SELECT COUNT(*) FROM papers')
total = c.fetchone()[0]

# Missing authors
c.execute("SELECT COUNT(*) FROM papers WHERE authors IS NULL OR authors = '' OR authors = '[]' OR authors = 'null'")
no_authors = c.fetchone()[0]

# Missing year
c.execute("SELECT COUNT(*) FROM papers WHERE year IS NULL")
no_year = c.fetchone()[0]

# Missing title
c.execute("SELECT COUNT(*) FROM papers WHERE title IS NULL OR title = ''")
no_title = c.fetchone()[0]

# Missing venue
c.execute("SELECT COUNT(*) FROM papers WHERE venue IS NULL OR venue = ''")
no_venue = c.fetchone()[0]

# Papers with ALL required fields complete
c.execute("""
    SELECT COUNT(*) FROM papers 
    WHERE authors IS NOT NULL AND authors != '' AND authors != '[]' AND authors != 'null'
    AND year IS NOT NULL
    AND title IS NOT NULL AND title != ''
""")
complete = c.fetchone()[0]

print(f"=== METADATA COMPLETENESS REPORT ===")
print(f"Total papers:        {total}")
print(f"Missing authors:     {no_authors}")
print(f"Missing year:        {no_year}")  
print(f"Missing title:       {no_title}")
print(f"Missing venue:       {no_venue} (optional for APA)")
print(f"---")
print(f"Complete (for APA):  {complete}")
print(f"Incomplete:          {total - complete}")

conn.close()
