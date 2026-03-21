import sqlite3
import os

db_path = "data/sme.db"
if not os.path.exists(db_path):
    print(f"Error: {db_path} not found")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM papers WHERE status = 'chunked';")
count = cursor.fetchone()[0]
print(f"Papers with status 'chunked': {count}")
conn.close()
