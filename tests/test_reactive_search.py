
import unittest
from unittest.mock import MagicMock, patch
import logging
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.retrieval.sequential_rag import SequentialRAG

# Configure logging
logging.basicConfig(level=logging.INFO)

class TestReactiveSearch(unittest.TestCase):
    def setUp(self):
        # Mock dependencies
        self.mock_llm = MagicMock()
        self.mock_reranker = MagicMock()
        self.mock_hybrid_search = MagicMock()
        
        # Setup mock hybrid search to return basic results
        self.mock_hybrid_search.search.return_value = []
        
        # Init RAG with mocked pipeline
        pipeline = {
            "llm": self.mock_llm,
            "reranker": self.mock_reranker,
            "hybrid_search": self.mock_hybrid_search,
            "embedder": MagicMock()
        }
        self.rag = SequentialRAG(pipeline)

    def test_audit_sufficient(self):
        """Test that Audit returns SUFFICIENT when LLM says so."""
        # Setup LLM response
        self.mock_llm.generate.return_value = "DECISION: SUFFICIENT"
        
        # Test inputs
        results = [{"title": "Paper A", "snippet": "Text A"}, {"title": "Paper B", "snippet": "Text B"}]
        decision, details = self.rag._audit_search_results("query", results, "model")
        
        self.assertEqual(decision, "SUFFICIENT")
        self.assertIsNone(details)

    def test_audit_missing(self):
        """Test that Audit returns MISSING with term when LLM says so."""
        self.mock_llm.generate.return_value = "DECISION: MISSING: specific term"
        
        results = [{"title": "Paper A", "snippet": "Text A"}]
        decision, details = self.rag._audit_search_results("query", results, "model")
        
        self.assertEqual(decision, "MISSING")
        self.assertEqual(details, "specific term")

    def test_audit_restructure(self):
        """Test that Audit returns RESTRUCTURE when LLM says so."""
        self.mock_llm.generate.return_value = "DECISION: RESTRUCTURE"
        
        results = [{"title": "Paper A", "snippet": "Text A"}]
        decision, details = self.rag._audit_search_results("query", results, "model")
        
        self.assertEqual(decision, "RESTRUCTURE")
        self.assertIsNone(details)

    def test_audit_empty_results(self):
        """Test that empty results trigger RESTRUCTURE automatically."""
        decision, details = self.rag._audit_search_results("query", [], "model")
        self.assertEqual(decision, "RESTRUCTURE")

if __name__ == '__main__':
    unittest.main()
