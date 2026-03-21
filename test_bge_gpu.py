import time
import torch
from src.retrieval.reranker import CrossEncoderReranker
from src.core.interfaces import RetrievalResult, Chunk

def run_test():
    print("=" * 60)
    print("BGE RERANKER GPU OPTIMIZATION TEST")
    print("=" * 60)
    
    # Check CUDA
    if not torch.cuda.is_available():
        print("❌ FATAL: CUDA is not available! PyTorch cannot see the GPU.")
        return
        
    print(f"✅ CUDA Available: {torch.cuda.get_device_name(0)}")
    print(f"Memory Allocated: {torch.cuda.memory_allocated() / 1e9:.2f} GB")
    print(f"Memory Reserved:  {torch.cuda.memory_reserved() / 1e9:.2f} GB")
    print()

    # Initialize Reranker via Pipeline Loader
    print("1. Initializing Reranker via Pipeline Loader...")
    from src.pipeline.loader import load_rag_pipeline_core
    t0 = time.time()
    
    # Use docker_config.yaml in container
    pipeline = load_rag_pipeline_core("config/docker_config.yaml")
    reranker = pipeline["reranker"]
    
    print(f"   Config Verification:")
    print(f"   - Model: {reranker.model_name}")
    print(f"   - Device: {reranker.device}")
    print(f"   - Batch Size: {reranker.batch_size}")
    print(f"   - Max Length: {reranker.max_length}")
    print(f"   - Dtype: {reranker.dtype_str}")
    
    t1 = time.time()
    
    print(f"   Done in {t1-t0:.2f}s")
    print(f"   Memory Allocated: {torch.cuda.memory_allocated() / 1e9:.2f} GB")
    print(f"   Memory Reserved:  {torch.cuda.memory_reserved() / 1e9:.2f} GB")
    print()
    
    # Create Mock Data (200 candidates, 1000 tokens each to test truncation)
    print("2. Generating 200 mock candidates (simulating heavy load)...")
    long_text = "This is a test document. " * 200  # ~1000 words
    
    mock_results = []
    for i in range(200):
        # We make one artificially highly relevant
        text = long_text if i != 42 else "The capital of France is Paris. This is the exact answer."
        score = 0.5  # initial mock score
        
        chunk = Chunk(
            chunk_id=f"doc_{i}",
            text=text,
            doi=f"10.000/mock_{i}"
        )
        mock_results.append(RetrievalResult(chunk=chunk, score=score, source="semantic"))
        
    print()
    
    # Run Reranking
    query = "What is the capital of France?"
    print(f"3. Running inference for query: '{query}'")
    print(f"   Batch size: 128 | Candidates: 200 | Max Length: 512")
    
    # Warmup pass (PyTorch initialization takes extra time on first run)
    print("   (Warming up graph...)")
    reranker.rerank(query, mock_results[:10], top_k=5)
    
    t_start = time.time()
    final_results = reranker.rerank(query, mock_results, top_k=5)
    t_end = time.time()
    
    latency = t_end - t_start
    print(f"   ✅ Reranking completed in {latency:.3f} seconds!")
    print(f"   Throughput: {200 / latency:.1f} pairs/sec")
    print()
    
    print("4. Top 3 Results:")
    for i, r in enumerate(final_results[:3]):
        snippet = r.chunk.text[:60] + "..." if len(r.chunk.text) > 60 else r.chunk.text
        print(f"   Rank {i+1} | Score: {r.score:.4f} | ID: {r.chunk.chunk_id}")
        print(f"     Text: {snippet}")
        
    print()
    print("5. Final GPU State:")
    print(f"   Memory Allocated: {torch.cuda.memory_allocated() / 1e9:.2f} GB")
    print(f"   Memory Reserved:  {torch.cuda.memory_reserved() / 1e9:.2f} GB")
    print("=" * 60)

if __name__ == "__main__":
    run_test()
