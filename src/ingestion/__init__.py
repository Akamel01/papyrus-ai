"""SME Research Assistant - Ingestion Module"""

from .pdf_parser import PyMuPDFParser, create_parser
from .chunker import HierarchicalChunker, create_chunker
from .preprocessor import TextPreprocessor, create_preprocessor
from .metadata_enricher import (
    enrich_batch_sync,
    enrich_all_missing,
    fetch_metadata_from_openalex,
    format_apa_reference
)

__all__ = [
    "PyMuPDFParser",
    "create_parser",
    "HierarchicalChunker", 
    "create_chunker",
    "TextPreprocessor",
    "create_preprocessor",
    "enrich_batch_sync",
    "enrich_all_missing",
    "fetch_metadata_from_openalex",
    "format_apa_reference",
]

