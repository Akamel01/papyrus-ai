#!/usr/bin/env python
"""
SME Research Assistant - Paper Ingestion Script

Ingests PDF papers from the database folder into the RAG system.
"""

import sys
import os
import logging
from pathlib import Path
from typing import List, Optional
from tqdm import tqdm
import argparse

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion import create_parser, create_chunker
from src.indexing import create_embedder, create_vector_store, create_bm25_index
from src.utils.helpers import load_config, batch_items
from src.core import Chunk

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PaperIngester:
    """
    Orchestrates the paper ingestion pipeline.
    """
    
    def __init__(self, config: dict = None):
        """Initialize ingester with config."""
        self.config = config or load_config()
        
        # Initialize components
        ingestion_config = self.config.get("ingestion", {})
        chunking_config = self.config.get("chunking", {})
        embedding_config = self.config.get("embedding", {})
        vector_config = self.config.get("vector_store", {})
        bm25_config = self.config.get("bm25", {})
        
        self.parser = create_parser(
            quality_threshold=ingestion_config.get("quality_threshold", 0.7)
        )
        
        self.chunker = create_chunker(
            chunk_size=chunking_config.get("chunk_size", 800),
            chunk_overlap=chunking_config.get("chunk_overlap", 150),
            min_chunk_size=chunking_config.get("min_chunk_size", 100)
        )
        
        self.embedder = create_embedder(
            model_name=embedding_config.get("model_name", "BAAI/bge-large-en-v1.5"),
            device=embedding_config.get("device", "cpu"),
            batch_size=embedding_config.get("batch_size", 64)
        )
        
        self.vector_store = create_vector_store(
            host=vector_config.get("host", "localhost"),
            port=vector_config.get("port", 6333),
            collection_name=vector_config.get("collection_name", "sme_papers"),
            embedding_dimension=embedding_config.get("dimension", 1024)
        )
        
        self.bm25_index = create_bm25_index(
            index_path=bm25_config.get("index_path", "data/bm25_index.pkl")
        )
        
        self.batch_size = ingestion_config.get("batch_size", 100)
    
    def ingest_papers(
        self,
        papers_dir: str,
        limit: Optional[int] = None,
        skip_existing: bool = True
    ) -> dict:
        """
        Ingest papers from directory.
        
        Args:
            papers_dir: Directory containing PDF files
            limit: Maximum number of papers to process
            skip_existing: Skip papers already in vector store
            
        Returns:
            Statistics dict
        """
        papers_path = Path(papers_dir)
        if not papers_path.exists():
            raise ValueError(f"Papers directory not found: {papers_dir}")
        
        # Get all PDF files
        pdf_files = list(papers_path.glob("*.pdf"))
        logger.info(f"Found {len(pdf_files)} PDF files")
        
        if limit:
            pdf_files = pdf_files[:limit]
            logger.info(f"Processing first {limit} files")
        
        # Statistics
        stats = {
            "total": len(pdf_files),
            "processed": 0,
            "failed": 0,
            "skipped": 0,
            "chunks_created": 0,
            "failed_files": []
        }
        
        # Ensure collection exists
        self.vector_store.create_collection()
        
        # All chunks for BM25
        all_chunks: List[Chunk] = []
        
        # Process in batches
        for batch in tqdm(
            list(batch_items(pdf_files, self.batch_size)),
            desc="Processing batches"
        ):
            batch_chunks = []
            
            for pdf_file in batch:
                try:
                    # Parse PDF
                    document = self.parser.parse(pdf_file)
                    
                    # Chunk document
                    chunks = self.chunker.chunk(document)
                    
                    if chunks:
                        batch_chunks.extend(chunks)
                        stats["processed"] += 1
                        stats["chunks_created"] += len(chunks)
                    else:
                        stats["skipped"] += 1
                        
                except Exception as e:
                    logger.warning(f"Failed to process {pdf_file.name}: {e}")
                    stats["failed"] += 1
                    stats["failed_files"].append({
                        "file": pdf_file.name,
                        "error": str(e)
                    })
            
            # Generate embeddings for batch
            if batch_chunks:
                try:
                    texts = [chunk.text for chunk in batch_chunks]
                    embeddings = self.embedder.embed(texts)
                    
                    # Attach embeddings to chunks
                    for chunk, embedding in zip(batch_chunks, embeddings):
                        chunk.embedding = embedding
                    
                    # Upsert to vector store
                    self.vector_store.upsert(batch_chunks)
                    
                    # Collect for BM25
                    all_chunks.extend(batch_chunks)
                    
                except Exception as e:
                    logger.error(f"Failed to index batch: {e}")
        
        # Build BM25 index
        if all_chunks:
            logger.info(f"Building BM25 index with {len(all_chunks)} chunks")
            self.bm25_index.index(all_chunks)
            self.bm25_index.save()
        
        # Log statistics
        logger.info(f"Ingestion complete:")
        logger.info(f"  Processed: {stats['processed']}")
        logger.info(f"  Failed: {stats['failed']}")
        logger.info(f"  Skipped: {stats['skipped']}")
        logger.info(f"  Total chunks: {stats['chunks_created']}")
        
        return stats


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Ingest papers into RAG system")
    parser.add_argument(
        "--papers-dir",
        default="DataBase/Papers",
        help="Directory containing PDF papers"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of papers to process"
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to config file"
    )
    
    args = parser.parse_args()
    
    try:
        config = load_config(args.config)
    except Exception as e:
        logger.warning(f"Could not load config: {e}, using defaults")
        config = {}
    
    ingester = PaperIngester(config)
    stats = ingester.ingest_papers(
        papers_dir=args.papers_dir,
        limit=args.limit
    )
    
    print(f"\nIngestion Statistics:")
    print(f"  Total files: {stats['total']}")
    print(f"  Processed: {stats['processed']}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Chunks created: {stats['chunks_created']}")
    
    if stats['failed_files']:
        print(f"\nFailed files:")
        for f in stats['failed_files'][:10]:
            print(f"  - {f['file']}: {f['error'][:50]}")


if __name__ == "__main__":
    main()
