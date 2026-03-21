#!/usr/bin/env python
import sys
import os
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.storage import DatabaseManager, StateStore

def seed_date(date_str: str, db_path: str = "data/sme.db"):
    print(f"Opening database at {db_path}...")
    db_manager = DatabaseManager(db_path)
    state_store = StateStore(db_manager)
    
    print(f"Setting last_discovery_date to {date_str}...")
    state_store.set("last_discovery_date", date_str)
    
    # Verify
    stored = state_store.get("last_discovery_date")
    print(f"Verified stored value: {stored}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed pipeline state")
    parser.add_argument("date", help="Date string YYYY-MM-DD")
    parser.add_argument("--db", default="data/sme.db", help="Path to DB")
    
    args = parser.parse_args()
    seed_date(args.date, args.db)
