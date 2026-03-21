"""SME Research Assistant - Indexing Module"""

from .embedder import create_embedder
# TransformerEmbedder is now in .embedder_local and should be used via create_embedder
from .embedder_local import TransformerEmbedder
from .vector_store import QdrantVectorStore, create_vector_store
from .bm25_index import BM25Index, create_bm25_index
from . import qdrant_optimizer

__all__ = [
    "TransformerEmbedder",
    "create_embedder",
    "QdrantVectorStore",
    "create_vector_store",
    "BM25Index",
    "create_bm25_index",
    "qdrant_optimizer",
]
