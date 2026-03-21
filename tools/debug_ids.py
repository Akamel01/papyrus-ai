
import sys
import os
import pickle
import glob
from qdrant_client import QdrantClient

# Helper to normalize ID (What Qdrant likely does)
import uuid

# Add project root to path so we can unpickle 'src.core.interfaces.Chunk'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def main():
    print("--- DEBUGGING ID FORMAT ---")
    
    # 1. Load Pickle ID
    pkl_files = glob.glob("data/interim_chunks/*.pkl")
    if not pkl_files:
        print("No pickles found.")
        return
        
    with open(pkl_files[0], "rb") as f:
        chunks = pickle.load(f)
        pickle_id = chunks[0].chunk_id
        
    print(f"PICKLE ID (Raw): '{pickle_id}' (Type: {type(pickle_id)})")
    
    # 2. Query Qdrant
    try:
        client = QdrantClient(host="localhost", port=6333)
        res = client.scroll(
            collection_name="sme_papers",
            limit=1,
            with_payload=False,
            with_vectors=False
        )
        points = res[0]
        if points:
            qdrant_id = points[0].id
            print(f"QDRANT ID (Raw): '{qdrant_id}' (Type: {type(qdrant_id)})")
            
            # Comparison Check
            print("\n--- COMPARISON ---")
            print(f"Direct Match? {str(pickle_id) == str(qdrant_id)}")
            
            # Check UUID conversion
            try:
                uuid_obj = uuid.UUID(pickle_id)
                print(f"Pickle -> UUID: '{str(uuid_obj)}'")
                print(f"UUID Match?     {str(uuid_obj) == str(qdrant_id)}")
            except:
                print("Pickle ID is not a valid UUID string.")
                
        else:
            print("Qdrant collection empty.")
            
    except Exception as e:
        print(f"Qdrant Error: {e}")

if __name__ == "__main__":
    main()
