
import sys
import os
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.retrieval.context_builder import ContextBuilder
from src.core.interfaces import RetrievalResult, Chunk

class TestContextAPA(unittest.TestCase):
    def setUp(self):
        self.db_path = Path("tests/test_sme.db")
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        
        # Create papers table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY,
                title TEXT,
                abstract TEXT,
                authors TEXT,
                year INTEGER,
                venue TEXT,
                doi TEXT UNIQUE,
                url TEXT,
                pdf_path TEXT,
                is_open_access INTEGER,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
        """)
        
        # Insert test paper with FULL metadata
        self.cursor.execute("""
            INSERT OR REPLACE INTO papers (id, title, authors, year, venue, doi)
            VALUES (1, 'Test Paper Title', '["Smith, J.", "Doe, A."]', 2023, 'Journal of Testing', '10.1234/test.1')
        """)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        # if self.db_path.exists():
        #     os.remove(self.db_path) 
        # Keep it for inspection if needed, or remove.

    def test_apa_reference_generation(self):
        # Initialize ContextBuilder with test DB
        builder = ContextBuilder(db_path=self.db_path)
        
        # Mock Chunk
        chunk = Chunk(
            chunk_id="1_0",
            text="This is a test chunk.",
            doi="10.1234/test.1",
            metadata={"title": "Test Paper Title"}
        )
        
        # Mock RetrievalResult
        retrieval_result = RetrievalResult(
            chunk=chunk,
            score=0.9,
            source="test"
        )
        
        # Build context
        context_str, used_results, references, doi_map = builder.build_context([retrieval_result])
        
        print("\n--- Context Output ---")
        print(context_str)
        print("----------------------")
        
        # Assertions
        # 1. Reference section should accept the paper
        # Note: ContextBuilder itself might not append the "References" header string unless specific format method is used?
        # Typically main.py appends the references list.
        # But let's check the references list return value.
        
        self.assertTrue(len(references) > 0)
        self.assertIn("Smith, J.", references[0])
        self.assertIn("(2023)", references[0])
        self.assertIn("Test Paper Title", references[0])
        
        # 2. Check context string for citation marker
        # Either [1] or (Smith, 2023) depending on format
        self.assertIn("[1]", context_str)
        self.assertIn("This is a test chunk.", context_str)

if __name__ == "__main__":
    unittest.main()
