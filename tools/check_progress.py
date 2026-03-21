
import sqlite3
import os

try:
    conn = sqlite3.connect('data/sme.db')
    c = conn.cursor()
    c.execute("SELECT value FROM pipeline_state WHERE key='metadata_update_last_offset'")
    row = c.fetchone()
    print(f"Progress Offset: {row[0] if row else 0}")
    
    # Also count how many have been updated in last 10 mins? 
    # Hard without updated_at on papers, but we have offset.
    
    conn.close()
except Exception as e:
    print(f"Error: {e}")
