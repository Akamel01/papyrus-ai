"""
SME Research Assistant - Multi-Process Parsing Worker

This module contains the stateless worker function for the ProcessPoolExecutor.
By keeping this in a separate module, we avoid pickling issues on Windows
related to nested functions or main-module dependencies.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.ingestion.pdf_parser import PyMuPDFParser
from src.ingestion.chunker import HierarchicalChunker
from src.core.interfaces import Chunk
from src.pipeline.streaming import PipelineItem

logger = logging.getLogger(__name__)

def process_paper_to_chunks(
    pdf_path: str,
    paper_metadata: Dict[str, Any],
    parser_config: Dict[str, Any],
    chunker_config: Dict[str, Any]
) -> List[Chunk]:
    """
    Stateless worker function to parse and chunk a single PDF.
    Runs in a separate process.
    """
    try:
        pdf_path_obj = Path(pdf_path)
        if not pdf_path_obj.exists():
            raise FileNotFoundError(f"PDF not found at {pdf_path}")

        # 1. Initialize Parser
        parser = PyMuPDFParser(
            quality_threshold=parser_config.get('quality_threshold', 0.7),
            use_markdown=parser_config.get('use_markdown', False)
        )

        # 2. Initialize Chunker
        chunker = HierarchicalChunker(
            chunk_size=chunker_config.get('chunk_size', 800),
            chunk_overlap=chunker_config.get('chunk_overlap', 150),
            min_chunk_size=chunker_config.get('min_chunk_size', 100),
            tokenizer_name=chunker_config.get('tokenizer', "cl100k_base")
        )

        # 3. Parse
        document = parser.parse(pdf_path_obj)
        if not document:
            raise ValueError("Parser returned no document")

        # 4. Chunk
        chunks = chunker.chunk(document)
        
        # 5. Inject metadata
        apa_ref = paper_metadata.get('apa_reference', "Reference unavailable")
        doi = paper_metadata.get('doi')
        title = paper_metadata.get('title')
        authors = paper_metadata.get('authors', [])
        year = paper_metadata.get('year')
        venue = paper_metadata.get('venue')
        citation_count = paper_metadata.get('citation_count', 0)

        for chunk in chunks:
            chunk.metadata.update({
                "title": title,
                "authors": authors,
                "year": year,
                "venue": venue,
                "citation_count": citation_count,
                "apa_reference": apa_ref,
                "doi": doi
            })
            if hasattr(chunk, 'doi'):
                chunk.doi = doi

        return chunks

    except Exception as e:
        logger.error(f"[PROCESS-WORKER] Failed to process {pdf_path}: {e}")
        raise
