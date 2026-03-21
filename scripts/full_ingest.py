#!/usr/bin/env python
"""
Full Scale Ingestion Script for SME RAG System (52k Papers).

Strategy:
1. Parallel Parsing: 20 CPU workers for PDF -> Text
2. Batch Embedding: GPU (CUDA) for Text -> Vector
3. Incremental Storage: Qdrant upsert per batch
4. Checkpointing: track progress to allow resuming
5. Delayed BM25: Build index once at the end
"""

import os
import sys
import logging
import json
import pickle
import time
from pathlib import Path
from typing import List, Dict, Set
from concurrent.futures import ProcessPoolExecutor
from tqdm import tqdm
import torch

# Force CUDA for main process
os.environ['CUDA_VISIBLE_DEVICES'] = '0'

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion import create_parser, create_chunker
from src.indexing import create_vector_store
from src.core import Chunk

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("ingestion.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
BATCH_SIZE = 1000  # Papers per super-batch
WORKERS = 20       # CPU cores for parsing
CHUNKS_DIR = Path("data/interim_chunks")
STATE_FILE = Path("data/ingestion_state.json")

def load_state() -> Set[str]:
    """Load processed filenames from state file."""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_state(processed: Set[str]):
    """Save processed filenames to state file."""
    with open(STATE_FILE, 'w') as f:
        json.dump(list(processed), f)

def worker_parse_file(file_path: Path) -> List[Chunk]:
    """
    Worker function to parse and chunk a single file.
    Running in a separate process, so it must instantiate its own parser/chunker.
    """
    try:
        # Re-instantiate locally to be process-safe
        parser = create_parser(quality_threshold=0.5)
        chunker = create_chunker(chunk_size=800, chunk_overlap=150)
        
        doc = parser.parse(file_path)
        chunks = chunker.chunk(doc)
        return chunks
    except Exception as e:
        # Return empty list on failure (logging handled by main)
        return []

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Full Scale Ingestion")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of papers to process")
    args = parser.parse_args()

    logger.info("Starting Full Scale Ingestion")
    
    # Complete Imports
    from sentence_transformers import SentenceTransformer
    from src.indexing.bm25_index import create_bm25_index
    
    # 1. Setup
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    papers_dir = Path("DataBase/Papers")
    all_pdfs = sorted(list(papers_dir.glob("*.pdf")))
    logger.info(f"Found {len(all_pdfs)} papers")
    
    # 2. Checkpoint
    processed_files = load_state()
    logger.info(f"Already processed: {len(processed_files)}")
    
    # Filter remaining
    remaining_pdfs = [p for p in all_pdfs if p.name not in processed_files]
    logger.info(f"Remaining to process: {len(remaining_pdfs)}")
    
    if args.limit:
        remaining_pdfs = remaining_pdfs[:args.limit]
        logger.info(f"Limiting run to {args.limit} papers")
    
    if not remaining_pdfs:
        logger.info("All papers processed! Moving to finalization.")
        finalize_bm25()
        return

    # 3. Model Loading (Main Process Only)
    logger.info("Loading Embedding Model on GPU...")
    model = SentenceTransformer("BAAI/bge-large-en-v1.5", device="cuda")
    vector_store = create_vector_store()
    vector_store.create_collection()
    
    # 4. Processing Loop
    total_batches = (len(remaining_pdfs) + BATCH_SIZE - 1) // BATCH_SIZE
    
    for i in range(total_batches):
        batch_pdfs = remaining_pdfs[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
        batch_id = f"{int(time.time())}_{i}"
        logger.info(f"Processing Batch {i+1}/{total_batches} ({len(batch_pdfs)} files)")
        
        # A. Parallel Parsing
        batch_chunks: List[Chunk] = []
        start_time = time.time()
        
        with ProcessPoolExecutor(max_workers=WORKERS) as executor:
            # Map returns iterator in order
            results = list(tqdm(
                executor.map(worker_parse_file, batch_pdfs), 
                total=len(batch_pdfs),
                desc="Parsing (CPU)"
            ))
            
            # Flatten results
            failed_count = 0
            for chunks in results:
                if chunks:
                    batch_chunks.extend(chunks)
                else:
                    failed_count += 1
        
        logger.info(f"Parsed {len(batch_pdfs)} files. Generated {len(batch_chunks)} chunks. Failed: {failed_count}")
        
        if not batch_chunks:
            continue
            
        # B. GPU Embedding
        logger.info("Embedding chunks (GPU)...")
        texts = [f"passage: {c.text}" for c in batch_chunks]
        
        embeddings = model.encode(
            texts,
            batch_size=64,
            show_progress_bar=True,
            normalize_embeddings=True,
            device="cuda"
        )
        
        # Attach embeddings
        for chunk, emb in zip(batch_chunks, embeddings):
            chunk.embedding = emb.tolist()
            
        # C. Storage
        logger.info("Upserting to Qdrant...")
        vector_store.upsert(batch_chunks)
        
        # D. Save Interim Data (for BM25)
        interim_path = CHUNKS_DIR / f"chunks_{batch_id}.pkl"
        with open(interim_path, 'wb') as f:
            pickle.dump(batch_chunks, f)
            
        # E. Update State
        for pdf in batch_pdfs:
            processed_files.add(pdf.name)
        save_state(processed_files)
        
        logger.info(f"Batch {i+1} complete. Time: {time.time() - start_time:.2f}s")
        
    # 5. Finalize
    finalize_bm25()

def finalize_bm25():
    """Build final BM25 index from all interim chunks."""
    from src.indexing.bm25_index import create_bm25_index
    
    logger.info("Finalizing: Building BM25 Index...")
    all_chunks = []
    
    # Load all pickles
    chunk_files = list(CHUNKS_DIR.glob("chunks_*.pkl"))
    logger.info(f"Loading {len(chunk_files)} chunk batches...")
    
    for cf in tqdm(chunk_files, desc="Loading Batches"):
        with open(cf, 'rb') as f:
            batch = pickle.load(f)
            all_chunks.extend(batch)
            
    logger.info(f"Total Chunks: {len(all_chunks)}")
    
    # Build Index
    bm25 = create_bm25_index()
    bm25.index(all_chunks)
    bm25.save()
    logger.info("BM25 Index Built and Saved!")

if __name__ == "__main__":
    main()
