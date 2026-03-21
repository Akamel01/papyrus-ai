import sqlite3
from pathlib import Path

DB_PATH = Path("sme.db")

def check_chunks_schema():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(chunks)")
    columns = cursor.fetchall()
    print("Chunks Table Schema:")
    for col in columns:
        print(col)
    conn.close()

if __name__ == "__main__":
    check_chunks_schema()
