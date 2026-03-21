
import sys
import os
import logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.acquisition.api_clients.semantic_scholar import SemanticScholarClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_s2_batch():
    client = SemanticScholarClient()
    
    # 1. Test Valid Simple DOI
    print("\n--- Testing Simple DOI ---")
    valid_doi = "10.1038/nrn3241"
    try:
        res = client.get_papers_by_dois([valid_doi])
        print(f"Success! Result count: {len(res)}")
        if res:
            print(f"Paper: {res[0].title}")
    except Exception as e:
        print(f"Failed: {e}")

    # 2. Test SICI DOI (Complex)
    print("\n--- Testing SICI DOI ---")
    # This SICI caused failures
    sici_doi = "10.1002/(sici)1097-0169(1999)43/2/137//aid-cm5/3.0.co;2-7" 
    try:
        res = client.get_papers_by_dois([sici_doi])
        print(f"Success! Result count: {len(res)}")
    except Exception as e:
        print(f"Failed: {e}")
        
    client.close()

if __name__ == "__main__":
    test_s2_batch()
