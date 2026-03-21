import sys
import time
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException

def test_connection():
    print("Testing connection to qdrant:6333...", flush=True)
    try:
        client = QdrantClient(host="qdrant", port=6333, timeout=5)
        # Try to get collections to verify actual connectivity
        collections = client.get_collections()
        print(f"SUCCESS: Connected to Qdrant! Found {len(collections.collections)} collections.", flush=True)
        return True
    except Exception as e:
        print(f"FAILURE: Could not connect to Qdrant: {e}", flush=True)
        return False

if __name__ == "__main__":
    success = test_connection()
    if not success:
        sys.exit(1)
