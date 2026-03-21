"""
Tests for the Acquisition Module
"""
import pytest
from unittest.mock import MagicMock, patch
from src.acquisition.api_clients.openalex import OpenAlexClient
from src.acquisition.paper_discoverer import PaperDiscoverer

class TestOpenAlexClient:
    @patch('src.acquisition.api_clients.openalex.requests.Session')
    def test_search_papers(self, mock_session):
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "doi": "https://doi.org/10.1234/test",
                    "title": "Test Paper",
                    "authorships": [{"author": {"display_name": "John Doe"}}],
                    "publication_year": 2023,
                    "open_access": {"is_oa": True, "oa_url": "http://example.com/pdf"}
                }
            ],
            "meta": {"next_cursor": None}
        }
        mock_session.return_value.get.return_value = mock_response
        
        client = OpenAlexClient()
        papers = client.search_papers("test query")
        
        assert len(papers) == 1
        assert papers[0].doi == "10.1234/test"
        assert papers[0].title == "Test Paper"

class TestPaperDiscoverer:
    def test_discover_deduplication(self):
        # Mock class with no clients
        discoverer = PaperDiscoverer(
            enable_openalex=False,
            enable_semantic_scholar=False,
            enable_arxiv=False
        )
        
        # Prepare mock papers
        from src.acquisition.paper_discoverer import DiscoveredPaper
        
        paper1 = DiscoveredPaper(
            doi="10.1234/test",
            title="Test Paper",
            citation_count=10,
            source="source1",
            year=2023
        )
        
        paper2 = DiscoveredPaper(
            doi="10.1234/test", # Same DOI
            title="Test Paper",
            citation_count=20, # Higher citation count
            source="source2",
            year=2023
        )
        
        # Mock _search_source to return these papers
        # We need to set clients manually to trigger the loop
        discoverer.clients = {"source1": MagicMock(), "source2": MagicMock()}
        
        def mock_search(source_name, *args, **kwargs):
            if source_name == "source1":
                return [paper1]
            return [paper2]
            
        discoverer._search_source = MagicMock(side_effect=mock_search)
        
        # Run discovery
        discovered = discoverer.discover(["test"])
        
        # Should have 1 paper (deduplicated)
        assert len(discovered) == 1
        # Should persist the one with higher citation count (paper2)
        assert discovered[0].citation_count == 20
        assert discovered[0].source == "source2"
