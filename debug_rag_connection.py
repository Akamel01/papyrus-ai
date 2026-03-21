
import sys
import os
from pathlib import Path
import time

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from src.utils.helpers import load_config
    from src.retrieval import create_hybrid_search, create_reranker
    from src.generation import create_ollama_client
    print("✅ Imports successful")
except ImportError as e:
    print(f"❌ Import failed: {e}")
    sys.exit(1)

def test_connection():
    print("\n--- Starting RAG Connection Test ---\n")
    
    # 1. Load Config
    try:
        config = load_config()
        print("✅ Config loaded")
    except Exception as e:
        print(f"❌ Config load failed: {e}")
        return

    # 2. Test LLM (Ollama)
    print("\n[Testing 1/2] LLM Connection (Ollama)...")
    try:
        model_name = config.get("generation", {}).get("model_name", "gemma:7b")
        base_url = config.get("generation", {}).get("base_url", "http://localhost:11434")
        print(f"Target: {base_url} (Model: {model_name})")
        
        llm = create_ollama_client(model_name=model_name, base_url=base_url)
        start = time.time()
        response = llm.generate("Hello, are you working?", max_tokens=10)
        elapsed = time.time() - start
        
        if response and len(response) > 0:
            print(f"✅ LLM Connected! (Response in {elapsed:.2f}s): {response.strip()}")
        else:
            print("❌ LLM returned empty response")
    except Exception as e:
        print(f"❌ LLM Connection failed: {e}")

    # 3. Test Retriever (Hybrid Search)
    print("\n[Testing 2/2] Retriever Connection (Embeddings/VectorDB)...")
    try:
        hybrid_search = create_hybrid_search(config)
        print("✅ HybridSearch initialized")
        
        # Simple search
        query = "test query"
        print(f"Searching for: '{query}'...")
        start = time.time()
        results = hybrid_search.search(query, top_k=3)
        elapsed = time.time() - start
        
        print(f"✅ Search completed in {elapsed:.2f}s")
        print(f"Found {len(results)} results")
        for i, res in enumerate(results):
            print(f"  Result {i+1}: Score={res.score:.4f}, Source={res.chunk.metadata.get('title', 'Unknown')}")
            
    except Exception as e:
        print(f"❌ Retriever Test failed: {e}")

if __name__ == "__main__":
    test_connection()
