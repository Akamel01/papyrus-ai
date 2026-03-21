import sqlite3
import pandas as pd
import shutil
from pathlib import Path

# Copy the DB to avoid locking the active stream
db_source = Path("/app/data/sme.db")
db_copy = Path("/tmp/sme_copy.db")

shutil.copy2(db_source, db_copy)

# Retrieve stats
try:
    c = sqlite3.connect(db_copy)
    df = pd.read_sql_query("SELECT status, count(*) as count FROM papers GROUP BY status ORDER BY count DESC", c)
    print("\nDATABASE STATUS BREAKDOWN:")
    print("-" * 30)
    print(df.to_string(index=False))
except Exception as e:
    print(f"Error querying DB: {e}")
