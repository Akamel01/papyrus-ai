
import torch
import sys

def check_env():
    print("--- Environment Check ---")
    print(f"Python: {sys.version}")
    
    # 1. CUDA
    try:
        cuda_available = torch.cuda.is_available()
        print(f"CUDA Available: {cuda_available}")
        if cuda_available:
            print(f"Device Name: {torch.cuda.get_device_name(0)}")
    except Exception as e:
        print(f"CUDA Check Failed: {e}")

    # 2. Embedding Model
    print("\n--- Model Check ---")
    try:
        from sentence_transformers import SentenceTransformer
        model_name = "BAAI/bge-large-en-v1.5"
        print(f"Loading {model_name}...")
        model = SentenceTransformer(model_name, device='cuda' if cuda_available else 'cpu')
        
        vec = model.encode("query: Hello world")
        print(f"Embedding Success. Vector Length: {len(vec)}")
        print(f"Output Sample: {vec[:3]}...")
    except Exception as e:
        print(f"Model Inference Failed: {e}")
        # Print full traceback
        import traceback
        traceback.print_exc()

    # 3. Network Check (Internal Qdrant)
    print("\n--- Network Check ---")
    try:
        from qdrant_client import QdrantClient
        print("Connecting to qdrant:6333...")
        client = QdrantClient(host="qdrant", port=6333)
        cols = client.get_collections()
        print(f"Connection Success. Collections: {cols}")
        count = client.get_collection("sme_papers").points_count
        print(f"Points in 'sme_papers': {count}")
    except Exception as e:
        print(f"Qdrant Connection Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_env()
