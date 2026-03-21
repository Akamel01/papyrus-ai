
import os
import sys
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

def debug_search():
    print("Initializing...")
    
    # 1. Connect to Qdrant (Host Port 6334 based on my diagnosis)
    try:
        client = QdrantClient(host="localhost", port=6334)
        print(f"Connected to Qdrant. Collections: {client.get_collections()}")
        count = client.get_collection("sme_papers").points_count
        print(f"Points in 'sme_papers': {count}")
    except Exception as e:
        print(f"Failed to connect to Qdrant: {e}")
        return

    # 2. Load Model
    model_name = "BAAI/bge-large-en-v1.5"
    print(f"Loading model {model_name}...")
    try:
        model = SentenceTransformer(model_name)
        print("Model loaded.")
    except Exception as e:
        print(f"Failed to load model: {e}")
        return

    # 3. Embed Query
    query = "Road safety assessment"
    print(f"Embedding query: '{query}'")
    # Note: BGE requires "query: " prefix for queries!
    vec = model.encode(f"query: {query}", normalize_embeddings=True)
    print(f"Vector sample: {vec[:5]}... (Len: {len(vec)})")

    # 4. Search
    print("Searching...")
    try:
        results = client.query_points(
            collection_name="sme_papers",
            query=vec,
            limit=5
        ).points
        print(f"Found {len(results)} results.")
        for r in results:
            print(f" - [{r.score:.4f}] ID: {r.id}")
            if r.payload:
                print(f"   Title: {r.payload.get('metadata', {}).get('title', 'No Title')}")
    except Exception as e:
        print(f"Search failed: {e}")

if __name__ == "__main__":
    debug_search()
