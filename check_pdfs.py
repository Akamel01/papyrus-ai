import sqlite3

conn = sqlite3.connect("data/sme.db")

# Check downloaded papers with/without pdf_path
r1 = conn.execute("SELECT COUNT(*) FROM papers WHERE status='downloaded' AND pdf_path IS NOT NULL").fetchone()
r2 = conn.execute("SELECT COUNT(*) FROM papers WHERE status='downloaded' AND pdf_path IS NULL").fetchone()
print(f"Downloaded with pdf_path: {r1[0]}")
print(f"Downloaded without pdf_path: {r2[0]}")

# Show the first 5 downloaded papers to understand what they look like
rows = conn.execute("SELECT unique_id, pdf_path, updated_at FROM papers WHERE status='downloaded' ORDER BY updated_at DESC LIMIT 10").fetchall()
print(f"\nFirst 10 downloaded papers (newest first):")
for uid, pdf, updated in rows:
    print(f"  {uid} | pdf={pdf} | updated={updated}")

# Count recently embedded (from this run)
recent = conn.execute("SELECT COUNT(*) FROM papers WHERE status='embedded' ORDER BY updated_at DESC").fetchone()
print(f"\nTotal embedded: {recent[0]}")

# Check if the 14 we just embedded are there
recent_papers = conn.execute("SELECT unique_id, updated_at FROM papers WHERE status='embedded' ORDER BY updated_at DESC LIMIT 20").fetchall()
print(f"\nMost recently embedded papers:")
for uid, updated in recent_papers:
    print(f"  {uid} | {updated}")

conn.close()
