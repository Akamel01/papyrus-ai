#!/usr/bin/env python3
"""
Migration: Add user_id column to papers table for multi-user support.

This migration:
1. Adds user_id TEXT column to papers table
2. Creates indexes for user_id filtering
3. Existing papers get user_id = NULL (shared/legacy papers)

Run: python scripts/migrate_add_user_id.py
"""

import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

DB_PATH = Path("data/sme.db")


def migrate():
    """Add user_id column to papers table."""
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        print("Run the main application first to create the database.")
        return False

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(papers)")
        columns = [col[1] for col in cursor.fetchall()]

        if "user_id" in columns:
            print("Column 'user_id' already exists in papers table. Migration not needed.")
            return True

        print("Adding 'user_id' column to papers table...")

        # Add the column
        cursor.execute("ALTER TABLE papers ADD COLUMN user_id TEXT")
        print("  - Column added successfully")

        # Create indexes
        print("Creating indexes for user_id...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_papers_user_id ON papers(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_papers_user_status ON papers(user_id, status)")
        print("  - Indexes created successfully")

        conn.commit()
        print("\nMigration completed successfully!")
        print("Existing papers have user_id = NULL (shared/legacy papers)")

        # Stats
        cursor.execute("SELECT COUNT(*) FROM papers")
        total = cursor.fetchone()[0]
        print(f"Total papers in database: {total}")

        return True

    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
        return False

    finally:
        conn.close()


if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
