
import logging
import sys
import os

# Ensure src is in path
sys.path.append(os.getcwd())

from src.retrieval.hybrid_search import create_hybrid_search
from src.indexing.bm25_tantivy import TantivyBM25Index


logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("verify_hybrid")

def main():
    print("DEBUG: Starting main...", file=sys.stderr)
    logger.info("Initializing Hybrid Search (expecting Tantivy)...")
    sys.stdout.flush()
    
    # Configure to use Tantivy
    config = {
        "bm25": {
            "index_path": "data/bm25_index_tantivy", # Correct path matches build script
            "tokenizer": "word"
        },
        "embedding": {
            "device": "cuda",
            "model_name": "Qwen/Qwen3-Embedding-8B",
            "quantization": "4bit"
        },
        "vector_store": {
            "host": "qdrant",
            "port": 6333,
            "timeout": 60
        },
        "retrieval": {
            "bm25_weight": 0.25,
            "semantic_weight": 0.75,
            "top_k_initial": 1000
        }
    }
    
    print("DEBUG: Creating HybridSearch...", file=sys.stderr)
    try:
        hybrid_search = create_hybrid_search(config)
        print("DEBUG: HybridSearch created.", file=sys.stderr)
    except Exception as e:
        print(f"DEBUG: Failed to create HybridSearch: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return
    
    # Verify it's using Tantivy
    if isinstance(hybrid_search.bm25_index, TantivyBM25Index):
        logger.info("✅ HybridSearch is using TantivyBM25Index")
    else:
        logger.error(f"❌ HybridSearch is using {type(hybrid_search.bm25_index)}")
        return

    # Verify Optimizer Injection
    if hasattr(hybrid_search.vector_store, '_opt'):
        logger.info(f"✅ Vector Store Optimized Params: {hybrid_search.vector_store._opt}")
    else:
        logger.warning("❌ Vector Store missing '_opt' attribute")

    query = "Extreme Value Theory"
    logger.info(f"Running query: '{query}'")
    sys.stdout.flush()
    
    results = hybrid_search.search(query, top_k=50)
    
    logger.info(f"Found {len(results)} results.")
    for i, res in enumerate(results):
        logger.info(f"{i+1}. [{res.score:.4f}] {res.chunk.metadata.get('title', 'No Title')} (Source: {res.source})")
        # Check if text is present (hydration worked)
        if res.chunk.text:
            logger.info(f"   Text snippet: {res.chunk.text[:100]}...")
        else:
            logger.warning("   ❌ Text missing (Hydration failed?)")

if __name__ == "__main__":
    main()
