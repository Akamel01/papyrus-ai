#!/usr/bin/env python
"""
Fast GPU-optimized paper ingestion for SME RAG system.
"""

import sys
import os
import logging
from pathlib import Path
from typing import List
from tqdm import tqdm
import argparse
import torch

# Force CUDA
os.environ['CUDA_VISIBLE_DEVICES'] = '0'

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Fast GPU ingestion")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    
    # Check CUDA
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"CUDA version: {torch.version.cuda}")
    
    # Import after CUDA env set
    from sentence_transformers import SentenceTransformer
    from src.ingestion import create_parser, create_chunker
    from src.indexing import create_vector_store, create_bm25_index
    from src.core import Chunk
    
    # Load embedding model on GPU
    print("\nLoading BGE model on CUDA...")
    model = SentenceTransformer("BAAI/bge-large-en-v1.5", device="cuda")
    print(f"Model loaded on: {model.device}")
    
    # Create other components
    pdf_parser = create_parser(quality_threshold=0.5)  # Lower threshold for speed
    chunker = create_chunker(chunk_size=800, chunk_overlap=150)
    vector_store = create_vector_store()
    vector_store.create_collection()
    bm25_index = create_bm25_index()
    
    # Get PDFs
    papers_dir = Path("DataBase/Papers")
    pdf_files = list(papers_dir.glob("*.pdf"))[:args.limit]
    print(f"\nProcessing {len(pdf_files)} papers...")
    
    all_chunks: List[Chunk] = []
    processed = 0
    failed = 0
    
    # Process PDFs
    for pdf_file in tqdm(pdf_files, desc="Parsing PDFs"):
        try:
            doc = pdf_parser.parse(pdf_file)
            chunks = chunker.chunk(doc)
            all_chunks.extend(chunks)
            processed += 1
        except Exception as e:
            failed += 1
    
    print(f"\nParsed: {processed} papers, {len(all_chunks)} chunks, {failed} failed")
    
    # Batch embed on GPU
    print(f"\nEmbedding {len(all_chunks)} chunks on GPU (batch size: {args.batch_size})...")
    texts = [f"passage: {c.text}" for c in all_chunks]
    
    embeddings = model.encode(
        texts,
        batch_size=args.batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
        device="cuda"
    )
    
    print(f"Embeddings shape: {embeddings.shape}")
    
    # Attach to chunks
    for chunk, emb in zip(all_chunks, embeddings):
        chunk.embedding = emb.tolist()
    
    # Upsert to Qdrant
    print("\nUpserting to Qdrant...")
    vector_store.upsert(all_chunks)
    
    # Build BM25
    print("Building BM25 index...")
    bm25_index.index(all_chunks)
    bm25_index.save()
    
    # Verify
    count = vector_store.count()
    print(f"\n✅ Complete! Qdrant count: {count}")
    print(f"   Processed: {processed}, Failed: {failed}, Chunks: {len(all_chunks)}")

if __name__ == "__main__":
    main()
