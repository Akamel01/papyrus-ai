
import logging
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.acquisition.paper_discoverer import PaperDiscoverer

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("SearchTest")

def test_search_syntax():
    print("="*60)
    print("SEARCH SYNTAX VERIFICATION TOOL")
    print("="*60)
    print("This script tests how different APIs handle your search keywords.")
    print("It will run queries and show you the first 3 titles found.\n")

    # Initialize Discoverer (Enable all clients)
    discoverer = PaperDiscoverer(
        email="test@example.com", 
        enable_openalex=True,
        enable_semantic_scholar=True, # Might be rate limited without key, but fine for test
        enable_arxiv=True,
        enable_crossref=True
    )

    # Test Cases
    tests = [
        {
            "name": "Exact Phrase Discovery",
            "query": '"Peaks-Over-Threshold"', 
            "description": "Should find papers with this EXACT phrase."
        },
        {
            "name": "Boolean Logic Discovery",
            "query": '(Bayesian AND conflicts)',
            "description": "Should find papers unrelated to just 'Bayesian' generic stats."
        }
    ]

    for test in tests:
        query = test["query"]
        print(f"\n[TEST] {test['name']}")
        print(f"Query: {query}")
        print(f"Goal:  {test['description']}")
        print("-" * 60)

        for source, client in discoverer.clients.items():
            print(f"\n  > Testing Source: {source.upper()}...")
            try:
                # Use the internal _search_source to get raw results list
                # We perform a small search (limit 3)
                results = discoverer._search_source(
                    source_name=source,
                    client=client,
                    keyword=query,
                    filters={"min_year": 2023}, # Recent papers only
                    max_results=3
                )
                
                if not results:
                    print(f"    [!] No results found.")
                else:
                    for i, p in enumerate(results[:3]):
                        print(f"    {i+1}. {p.title[:100]}...")
                        
            except Exception as e:
                print(f"    [x] Error: {e}")

    print("\n" + "="*60)
    print("VERIFICATION COMPLETE")
    print("Check the titles above. If they look relevant, your syntax is working.")
    print("="*60)

if __name__ == "__main__":
    test_search_syntax()
