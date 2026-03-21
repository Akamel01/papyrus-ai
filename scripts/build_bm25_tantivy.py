
import os
import time
import logging
import argparse
import sys
from pathlib import Path
from qdrant_client import QdrantClient

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.indexing.bm25_tantivy import TantivyBM25Index

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("build_bm25")

def main():
    parser = argparse.ArgumentParser(description="Build Tantivy BM25 index from Qdrant")
    parser.add_argument("--host", default="qdrant", help="Qdrant host")
    parser.add_argument("--port", type=int, default=6333, help="Qdrant port")
    parser.add_argument("--collection", default="sme_papers", help="Source collection name")
    parser.add_argument("--index-path", default="data/bm25_index_tantivy", help="Path to Tantivy index directory")
    parser.add_argument("--batch-size", type=int, default=2000, help="Scroll batch size")
    parser.add_argument("--heap-size", type=int, default=128, help="Tantivy writer heap size in MB")
    parser.add_argument("--commit-interval", type=int, default=20000, help="Commit every N documents")
    parser.add_argument("--num-threads", type=int, default=0, help="Number of indexing threads (0=auto)")
    parser.add_argument("--resume", action="store_true", help="Resume from previous state if available")
    args = parser.parse_args()

    # Connect to Qdrant
    logger.info(f"Connecting to Qdrant at {args.host}:{args.port}...")
    try:
        client = QdrantClient(host=args.host, port=args.port, timeout=60)
        info = client.get_collection(args.collection)
        logger.info(f"Source Collection: {args.collection} ({info.points_count:,} points)")
    except Exception as e:
        logger.error(f"Failed to connect to Qdrant: {e}")
        return

    # Initialize Tantivy Index
    logger.info(f"Initializing Tantivy index at '{args.index_path}'...")
    bm25 = TantivyBM25Index(index_path=args.index_path)
    
    # Build
    start_time = time.time()
    try:
        count = bm25.build_from_qdrant(
            client=client,
            collection_name=args.collection,
            batch_size=args.batch_size,
            heap_size_mb=args.heap_size,
            commit_interval=args.commit_interval,
            num_threads=args.num_threads,
            resume=args.resume
        )
        elapsed = time.time() - start_time
        logger.info(f"✅ Build Complete! Indexed {count:,} documents in {elapsed/60:.2f} minutes.")
        logger.info(f"Index size: {get_dir_size(args.index_path)/1024/1024:.2f} MB")
        
    except Exception as e:
        logger.error(f"Build Failed: {e}")
        import traceback
        traceback.print_exc()

def get_dir_size(path):
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total += os.path.getsize(fp)
    return total

if __name__ == "__main__":
    main()
