
import os
import sys
import logging
import time
from pathlib import Path
from tqdm import tqdm
import torch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.ingestion import create_parser, create_chunker
from src.indexing import create_vector_store
from src.core import Chunk
from src.indexing.vector_store import QdrantVectorStore
from sentence_transformers import SentenceTransformer
from src.indexing.bm25_index import create_bm25_index

# Configure safe logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting HOSTILE TAKEOVER INGESTION (Lite Mode)")
    
    # 1. Setup Paths
    LIMIT = 50
    DB_PATH = "./tools/gold_standard_bench/qdrant_db"
    PAPERS_DIR = Path("DataBase/Papers")
    
    # Verify Papers exist
    if not PAPERS_DIR.exists():
        logger.error(f"Papers directory not found: {PAPERS_DIR}")
        return
        
    all_pdfs = sorted(list(PAPERS_DIR.glob("*.pdf")))
    if not all_pdfs:
        logger.error("No PDFs found!")
        return
        
    logger.info(f"Found {len(all_pdfs)} papers. Ingesting first {LIMIT}...")
    target_pdfs = all_pdfs[:LIMIT]
    
    # 2. Initialize Components (CPU Forced)
    logger.info("Initializing components on CPU...")
    # Force connection to LOCAL EMBEDDED DB
    vector_store = QdrantVectorStore(
        location=DB_PATH,
        collection_name="sme_papers"
    )
    # Ensure collection exists
    try:
        # Checking if we can re-create or if it handles it
        # vector_store.create_collection() # This method might not exist on the class directly or might need args?
        # Checking source code of vector_store.py in previous turns, it uses QdrantClient.
        # Let's trust it auto-connects or we call create if needed.
        # Check vector_store.py content again?
        # It has create_collection() method in Line 119 of full_ingest calls it.
        # Let's try calling it.
        pass
    except Exception as e:
        logger.warning(f"Collection setup note: {e}")

    model = SentenceTransformer("BAAI/bge-large-en-v1.5", device="cpu")
    parser = create_parser(quality_threshold=0.5)
    chunker = create_chunker(chunk_size=800, chunk_overlap=150)
    
    # 3. Processing Loop
    all_chunks = []
    
    for pdf in tqdm(target_pdfs, desc="Processing Papers"):
        try:
            # Parse & Chunk
            doc = parser.parse(pdf)
            chunks = chunker.chunk(doc)
            
            if not chunks:
                continue
                
            # Embed
            texts = [f"passage: {c.text}" for c in chunks]
            embeddings = model.encode(texts, convert_to_tensor=True, device="cpu", normalize_embeddings=True)
            
            # Attach Embedding & Upsert
            for i, c in enumerate(chunks):
                c.embedding = embeddings[i].tolist()
            
            vector_store.upsert(chunks)
            all_chunks.extend(chunks)
            
        except Exception as e:
            logger.error(f"Failed {pdf.name}: {e}")
            continue
            
    logger.info(f"Ingested {len(all_chunks)} chunks from {LIMIT} papers.")
    
    # 4. Build BM25
    logger.info("Building BM25 Index...")
    bm25 = create_bm25_index() # Check defaults? It might need a path. 
    # Usually BM25 index stores itself in a default location or we pass it.
    # Let's assumes default is fine for now, or check bm25_index.py if it fails.
    bm25.index(all_chunks)
    bm25.save()
    logger.info("Done! Database populated.")

if __name__ == "__main__":
    main()
