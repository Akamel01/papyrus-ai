import logging
import time
from src.indexing.bm25_tantivy import TantivyBM25Index

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("check_tantivy")

def main():
    try:
        logger.info("Loading Tantivy index...")
        bm25 = TantivyBM25Index()
        
        # Check doc count
        searcher = bm25.index.searcher()
        num_docs = searcher.num_docs
        logger.info(f"Index contains {num_docs} documents.")
        
        # Run a simple query
        query = "flood"
        results = bm25.search(query, top_k=5)
        logger.info(f"Search for '{query}' returned {len(results)} results.")
        for r in results:
             logger.info(f" - {r.score:.4f} | ID: {r.chunk.chunk_id}")
             
        if num_docs > 0:
            logger.info("✅ Index is readable and contains data.")
        else:
            logger.warning("⚠️ Index is empty.")
            
    except Exception as e:
        logger.error(f"❌ Failed to read index: {e}")

if __name__ == "__main__":
    main()
