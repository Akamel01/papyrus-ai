import sqlite3
conn = sqlite3.connect('/app/data/sme.db')
cur = conn.cursor()
cur.execute("SELECT unique_id, status FROM papers WHERE unique_id LIKE '%10.1007/s40747-022-00795-6%'")
for row in cur.fetchall():
    print(f"ID: {row[0]}, Status: {row[1]}")
conn.close()
