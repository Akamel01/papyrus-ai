"""Debug complex DOI lookup via OpenAlex and Semantic Scholar"""
import sys
import os
import urllib.parse
# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.acquisition.api_clients.openalex import OpenAlexClient
from src.acquisition.api_clients.semantic_scholar import SemanticScholarClient

# Complex SICI DOI that failed
doi = "10.1002/(sici)1097-0169(1999)43/2/137//aid-cm5/3.0.co;2-7"

print(f"Testing DOI: {doi}")

# 1. OpenAlex URL-direct lookup
client = OpenAlexClient()
print("\n--- OpenAlex Direct ---")
try:
    # Manual request logic to test encoding
    # Try 1: As is (what current code likely does roughly)
    print("Attempt 1: Standard lookup")
    res = client.get_paper_by_doi(doi)
    print(f"Result: {res.title if res else 'None'}")
except Exception as e:
    print(f"Error: {e}")

try:
    # Try 2: Double encoded?
    print("Attempt 2: URL Encoded")
    encoded_doi = urllib.parse.quote(doi, safe='')
    print(f"Encoded: {encoded_doi}")
    # We can't easily force the client to use this specialized path without private method access
    # But let's try search_by_dois
except Exception as e:
    print(f"Error: {e}")

print("\n--- OpenAlex Search Filter ---")
try:
    # Test search_by_dois
    res_list = client.search_by_dois([doi])
    print(f"Found: {len(res_list)}")
    if res_list:
        print(f"Title: {res_list[0].title}")
except Exception as e:
    print(f"Error: {e}")

# 2. Semantic Scholar
print("\n--- Semantic Scholar ---")
try:
    ss_client = SemanticScholarClient()
    res = ss_client.get_paper_by_doi(doi)
    print(f"Result: {res.title if res else 'None'}")
    if res:
        print(f"Authors: {res.authors}")
        print(f"Year: {res.year}")
except Exception as e:
    print(f"Error: {e}")

client.close()
