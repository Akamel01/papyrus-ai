"""Debug simple failed DOI lookup"""
import sys
import os
# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.acquisition.api_clients.openalex import OpenAlexClient
from src.acquisition.api_clients.semantic_scholar import SemanticScholarClient

# Simple DOI that failed in sample
doi = "10.1001/jama.293.3.287"

print(f"Testing DOI: {doi}")

# 1. OpenAlex
print("\n--- OpenAlex ---")
try:
    client = OpenAlexClient()
    res = client.get_paper_by_doi(doi)
    if res:
        print(f"Title: {res.title}")
        print(f"Authors: {res.authors}")
        print(f"Year: {res.year}")
    else:
        print("Not found")
except Exception as e:
    print(f"Error: {e}")

# 2. Semantic Scholar
print("\n--- Semantic Scholar ---")
try:
    ss_client = SemanticScholarClient()
    res = ss_client.get_paper_by_doi(doi)
    if res:
        print(f"Title: {res.title}")
        print(f"Authors: {res.authors}")
        print(f"Year: {res.year}")
    else:
        print("Not found")
except Exception as e:
    print(f"Error: {e}")
