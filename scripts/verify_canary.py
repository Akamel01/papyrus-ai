
import time
import logging
from qdrant_client import QdrantClient
from qdrant_client.http import models

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("canary")

def run_canary():
    # Wait for Qdrant to be ready
    print("Connecting to Qdrant...")
    for _ in range(5):
        try:
            client = QdrantClient(host="qdrant", port=6333)
            client.get_collections()
            break
        except Exception as e:
            print(f"Waiting... {e}")
            time.sleep(2)
            
    print("--- Canary Query Latency Test (Qdrant Direct) ---")
    
    # Get a real vector from the collection to use as query
    try:
        res = client.scroll(collection_name="sme_papers", limit=1, with_vectors=True)
    except Exception as e:
        print(f"Error accessing collection: {e}")
        return

    if not res[0]:
        print("Collection empty!")
        return
        
    query_vector = res[0][0].vector
    print(f"Using vector from point {res[0][0].id} as query")
    
    # Warmup
    print("Warming up...")
    for _ in range(5):
        client.query_points(
            collection_name="sme_papers",
            query=query_vector,
            limit=10,
            search_params=models.SearchParams(
                hnsw_ef=128,
                quantization=models.QuantizationSearchParams(
                    ignore=False,
                    rescore=True,
                    oversampling=2.0
                )
            )
        )
        
    # Measure
    latencies = []
    print("Running 10 queries...")
    for i in range(10):
        start = time.time()
        client.query_points(
            collection_name="sme_papers",
            query=query_vector,
            limit=20,
            search_params=models.SearchParams(
                hnsw_ef=128,
                quantization=models.QuantizationSearchParams(
                    ignore=False,
                    rescore=True,
                    oversampling=2.0
                )
            )
        )
        dur = (time.time() - start) * 1000
        latencies.append(dur)
        print(f"Query {i+1}: {dur:.2f} ms")
        
    avg_lat = sum(latencies) / len(latencies)
    print(f"\nAverage Latency: {avg_lat:.2f} ms")
    
    # Check config again
    info = client.get_collection("sme_papers")
    print(f"\nCollection Config Verified: m={info.config.hnsw_config.m}, on_disk={info.config.params.vectors.on_disk}")

if __name__ == "__main__":
    run_canary()
