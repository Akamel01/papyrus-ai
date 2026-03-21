#!/usr/bin/env python
"""
Optimized Full Scale Ingestion Script for SME RAG System (52k Papers).

Architecture: Producer-Consumer (Async)
- Producer Thread: Runs CPU ProcessPool to parse PDFs -> Queue
- Consumer Thread: Runs GPU Embedding on batches from Queue -> Qdrant

Features:
- Robust Error Handling: Falls back to serial processing if batch embedding fails.
- State Persistence: Resumes where it left off.
- Performance: Overlaps CPU and GPU work.
"""

import os
import sys
import logging
import json
import pickle
import time
import threading
import queue
import uuid
from pathlib import Path
from typing import List, Set, Optional, Tuple, Any
from concurrent.futures import ProcessPoolExecutor
from tqdm import tqdm
import argparse

# Force CUDA for main process
os.environ['CUDA_VISIBLE_DEVICES'] = '0'

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion import create_parser, create_chunker
from src.indexing import create_vector_store
from src.core import Chunk

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("ingestion_optimized.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
BATCH_SIZE = 1000   # Papers per super-batch
WORKERS = 20        # CPU cores for parsing
QUEUE_MAX_SIZE = 2  # Max batches in queue (prevent RAM overflow)
CHUNKS_DIR = Path("data/interim_chunks")
STATE_FILE = Path("data/ingestion_state.json")

# Sentinel object to signal end of queue
SENTINEL = object()

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
    """Worker function to parse and chunk a single file."""
    try:
        parser = create_parser(quality_threshold=0.5)
        chunker = create_chunker(chunk_size=800, chunk_overlap=150)
        doc = parser.parse(file_path)
        chunks = chunker.chunk(doc)
        return chunks
    except Exception:
        return []

def producer_task(
    pdf_batches: List[List[Path]], 
    output_queue: queue.Queue,
    workers: int
):
    """
    Producer: Parses batches of PDFs and puts (batch_index, chunks, pdf_names) into queue.
    Uses pebble for hard timeouts on stuck processes.
    """
    from pebble import ProcessPool
    from concurrent.futures import TimeoutError
    
    logger.info("Producer Thread Started")
    
    with ProcessPool(max_workers=workers) as pool:
        for i, batch_pdfs in enumerate(pdf_batches):
            logger.info(f"Producing Batch {i+1}/{len(pdf_batches)} ({len(batch_pdfs)} files)")
            start_time = time.time()
            
            # Submit all tasks
            future_to_pdf = {
                pool.schedule(worker_parse_file, args=(pdf,), timeout=30): pdf 
                for pdf in batch_pdfs
            }
            
            batch_chunks = []
            failed_count = 0
            timeout_count = 0
            
            # Process results as they complete
            failed_records = []
            for future in tqdm(future_to_pdf, total=len(batch_pdfs), desc=f"Parsing Batch {i+1}", leave=False):
                pdf = future_to_pdf[future]
                error_reason = None
                try:
                    chunks = future.result()
                    if chunks:
                        batch_chunks.extend(chunks)
                    else:
                        error_reason = "No content extracted"
                except TimeoutError:
                    error_reason = "Timeout (>30s)"
                    logger.warning(f"Timeout parsing {pdf.name}")
                    timeout_count += 1
                except Exception as e:
                    error_reason = f"Error: {str(e)}"
                    logger.warning(f"Error parsing {pdf.name}: {e}")
                
                if error_reason:
                    failed_count += 1
                    failed_records.append({
                        "file": pdf.name,
                        "error": error_reason,
                        "timestamp": time.time()
                    })

            # Write failed records to file safely
            if failed_records:
                with open("data/failed_ingestion.jsonl", "a") as f:
                    for record in failed_records:
                        f.write(json.dumps(record) + "\n")
            
            duration = time.time() - start_time
            logger.info(f"Produced Batch {i+1}: {len(batch_chunks)} chunks (Failed: {failed_count}, Timeouts: {timeout_count}) in {duration:.2f}s")
            
            # Put to queue
            output_queue.put((i, batch_chunks, [p.name for p in batch_pdfs]))
    
    # Signal done
    output_queue.put(SENTINEL)
    logger.info("Producer Thread Finished")

def consumer_task(output_queue: queue.Queue, total_batches: int):
    """
    Consumer: Takes parsed chunks from queue and runs GPU embedding.
    ROBUST VERSION: Includes Serial Fallback for corrupted batches.
    """
    logger.info("Consumer Thread Started (GPU Ready)")
    
    # Initialize GPU resources
    from sentence_transformers import SentenceTransformer
    from qdrant_client.http import models as qmodels # Importing point structs
    
    model = SentenceTransformer("BAAI/bge-large-en-v1.5", device="cuda")
    vector_store = create_vector_store()
    vector_store.create_collection()
    # Fix: QdrantVectorStore uses lazy loading via _get_client()
    client = vector_store._get_client()
    collection_name = vector_store.collection_name
    
    processed_count = 0
    state_processed = load_state()
    
    while True:
        item = output_queue.get()
        if item is SENTINEL:
            break
            
        batch_idx, chunks, pdf_names = item
        batch_id = f"{int(time.time())}_{batch_idx}"
        logger.info(f"Consuming Batch {batch_idx+1}: Embedding {len(chunks)} chunks...")
        
        start_time = time.time()
        
        if not chunks:
            logger.warning(f"Batch {batch_idx+1} is empty!")
            output_queue.task_done()
            continue
            
        # 1. Prepare Texts (Safely)
        # Handle cases where chunks might use .text or .page_content or be None
        valid_chunks: List[Chunk] = []
        texts: List[str] = []
        
        for c in chunks:
            if not c: continue
            # Try to get text from common attributes
            txt = getattr(c, 'text', None) or getattr(c, 'page_content', None)
            if txt and isinstance(txt, str) and len(txt.strip()) > 0:
                valid_chunks.append(c)
                texts.append(txt)
                
        if not texts:
            logger.warning(f"Batch {batch_idx+1} contained no valid text chunks after safe filtering.")
            output_queue.task_done()
            continue

        # 2. Embedding + Recovery Loop
        points = []
        
        try:
            # FAST PATH: Embed everything at once
            embeddings = model.encode(
                texts,
                batch_size=64,
                show_progress_bar=True,
                normalize_embeddings=True,
                device="cuda"
            )
            
            # Prepare points
            for i, chunk in enumerate(valid_chunks):
                # Ensure embedding is valid list
                emb = embeddings[i]
                if hasattr(emb, 'tolist'):
                    emb = emb.tolist()
                
                chunk.embedding = emb # Update chunk object
                
                points.append(qmodels.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=emb,
                    payload=chunk.metadata or {}
                ))
                
        except Exception as e:
            # SLOW PATH: Serial Fallback
            logger.error(f"Batch {batch_idx+1} CRASHED (Error: {e}). Switching to SERIAL mode to salvage valid chunks.")
            points = []
            
            for i, text in enumerate(texts):
                try:
                    # Encode SINGLE item
                    single_embedding = model.encode([text], normalize_embeddings=True, device="cuda")[0]
                    if hasattr(single_embedding, 'tolist'):
                        single_embedding = single_embedding.tolist()
                        
                    points.append(qmodels.PointStruct(
                        id=str(uuid.uuid4()),
                        vector=single_embedding,
                        payload=valid_chunks[i].metadata or {}
                    ))
                except Exception as inner_e:
                    logger.error(f"CORRUPT CHUNK FLAGGED: {text[:50]}... Error: {inner_e}")
                    continue # Skip the bad apple

        if not points:
             logger.warning(f"Batch {batch_idx+1} resulted in 0 points after embedding.")
             output_queue.task_done()
             continue

        # 3. Save Interim FIRST (Data Safety)
        # We save before upserting so we don't lose the expensive GPU work if DB connection fails
        interim_path = CHUNKS_DIR / f"chunks_{batch_id}.pkl"
        try:
            with open(interim_path, 'wb') as f:
                pickle.dump(chunks, f) 
        except Exception as e:
            logger.error(f"Failed to save interim chunks pkl: {e}")

        # 4. Upsert to Qdrant (Batched & Retried)
        # WinError 10053 mitigation: Send smaller packets
        UPSERT_BATCH_SIZE = 50 
        
        total_points = len(points)
        for i in range(0, total_points, UPSERT_BATCH_SIZE):
            sub_batch = points[i : i + UPSERT_BATCH_SIZE]
            
            # Retry loop for connection stability
            for attempt in range(3):
                try:
                    client.upsert(
                        collection_name=collection_name,
                        points=sub_batch
                    )
                    break # Success
                except Exception as e:
                    if attempt == 2:
                        logger.error(f"Failed to upsert sub-batch {i}-{i+len(sub_batch)} of Batch {batch_idx+1} after 3 attempts: {e}")
                    else:
                        time.sleep(1) # Backoff
        
        # 5. Update State (Only after safe save)
        
        # 4. Save Interim & Update State
        interim_path = CHUNKS_DIR / f"chunks_{batch_id}.pkl"
        try:
            with open(interim_path, 'wb') as f:
                pickle.dump(chunks, f) # Dump original chunks for BM25 later
        except Exception as e:
            logger.error(f"Failed to save interim chunks pkl: {e}")
            
        for name in pdf_names:
            state_processed.add(name)
        save_state(state_processed)
        
        # 5. Enrich metadata for newly added papers (Phase 12 integration)
        try:
            from src.ingestion.metadata_enricher import enrich_batch_sync
            batch_dois = list(set(c.doi for c in chunks if c.doi.startswith("10.")))
            if batch_dois:
                enriched = enrich_batch_sync(client, collection_name, batch_dois)
                logger.info(f"Enriched {enriched} papers with APA metadata")
        except Exception as e:
            logger.warning(f"Metadata enrichment skipped: {e}")
        
        duration = time.time() - start_time
        logger.info(f"Consumed Batch {batch_idx+1} in {duration:.2f}s. Total Papers: {len(state_processed)}")
        output_queue.task_done()
        
    logger.info("Consumer Thread Finished")

def finalize_bm25():
    """Build final BM25 index."""
    from src.indexing.bm25_index import create_bm25_index
    logger.info("Building Final BM25 Index...")
    all_chunks = []
    chunk_files = list(CHUNKS_DIR.glob("chunks_*.pkl"))
    
    for cf in tqdm(chunk_files, desc="Loading Batches"):
        with open(cf, 'rb') as f:
            batch = pickle.load(f)
            all_chunks.extend(batch)
            
    bm25 = create_bm25_index()
    bm25.index(all_chunks)
    bm25.save()
    logger.info("BM25 Index Saved!")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Discovery
    papers_dir = Path("DataBase/Papers")
    all_pdfs = sorted(list(papers_dir.glob("*.pdf")))
    processed_files = load_state()
    
    remaining_pdfs = [p for p in all_pdfs if p.name not in processed_files]
    if args.limit:
        remaining_pdfs = remaining_pdfs[:args.limit]
        
    if not remaining_pdfs:
        logger.info("All papers processed. Finalizing.")
        finalize_bm25()
        return

    logger.info(f"Processing {len(remaining_pdfs)} papers in batches of {BATCH_SIZE}")
    
    # Prepare Batches
    num_batches = (len(remaining_pdfs) + BATCH_SIZE - 1) // BATCH_SIZE
    batches = [
        remaining_pdfs[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
        for i in range(num_batches)
    ]
    
    # Setup Pipeline
    work_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
    
    # Start Threads
    producer = threading.Thread(
        target=producer_task,
        args=(batches, work_queue, WORKERS)
    )
    consumer = threading.Thread(
        target=consumer_task,
        args=(work_queue, num_batches)
    )
    
    producer.start()
    consumer.start()
    
    producer.join()
    consumer.join()
    
    finalize_bm25()
    logger.info("Full Scale Ingestion Complete!")
    
    # --- Auto-Trigger Remediation ---
    logger.info("Triggering Remediation Pipeline for failed files...")
    import subprocess
    import sys # Ensure sys is imported or available from module scope
    try:
        subprocess.run([sys.executable, "scripts/remediate_failures.py"], check=False)
    except Exception as e:
        logger.error(f"Failed to trigger remediation script: {e}")
        
    logger.info("Pipeline Finished.")

if __name__ == "__main__":
    main()
