"""
SME Research Assistant - BM25 Index

Keyword-based search using BM25 algorithm with lifecycle management.

Lifecycle:
  - Metadata sidecar (bm25_index_meta.json) tracks build timestamp & point count
  - is_stale() compares Qdrant point count vs last build to detect drift
  - rebuild_from_qdrant() scrolls text payloads and rebuilds index from scratch
  - Smart-skip: weekly scheduled rebuild skips if point count hasn't changed
"""

import json
import pickle
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any
import re

from src.core.interfaces import KeywordIndex, Chunk, RetrievalResult
from src.core.exceptions import RetrievalError

logger = logging.getLogger(__name__)

# BM25 lifecycle constants
BM25_STALENESS_THRESHOLD = 0.05  # 5% point count drift triggers rebuild


class BM25Index(KeywordIndex):
    """
    BM25 keyword search index.
    """
    
    # Common English stop words
    STOP_WORDS = {
        'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
        'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the',
        'to', 'was', 'were', 'will', 'with', 'the', 'this', 'but', 'they',
        'have', 'had', 'what', 'when', 'where', 'who', 'which', 'why', 'how'
    }
    
    def __init__(
        self,
        index_path: str = "data/bm25_index.pkl",
        remove_stopwords: bool = True,
        tokenizer_type: str = "word"
    ):
        """
        Initialize BM25 index.

        Args:
            index_path: Path to save/load the index
            remove_stopwords: Whether to remove stop words
            tokenizer_type: Type of tokenization ("word" or "whitespace")
        """
        self.index_path = Path(index_path)
        self.remove_stopwords = remove_stopwords
        self.tokenizer_type = tokenizer_type

        self._bm25 = None
        self._chunks: List[Chunk] = []
        self._tokenized_corpus: List[List[str]] = []

        # Metadata sidecar for lifecycle tracking
        self._metadata_path = self.index_path.with_suffix(".meta.json")
        self._metadata: Dict = {}
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text for BM25."""
        # Lowercase
        text = text.lower()
        
        if self.tokenizer_type == "word":
            # Split on non-alphanumeric (default)
            tokens = re.findall(r'\b\w+\b', text)
        else:
            # Simple whitespace split
            tokens = text.split()
        
        if self.remove_stopwords:
            tokens = [t for t in tokens if t not in self.STOP_WORDS and len(t) > 2]
        
        return tokens
    
    # ... (rest of methods unchanged until create_bm25_index) ...

    def index(self, chunks: List[Chunk]) -> None:
        """
        Index chunks for keyword search.
        
        Args:
            chunks: List of chunks to index
        """
        if not chunks:
            return
        
        try:
            from rank_bm25 import BM25Okapi
            
            logger.info(f"Indexing {len(chunks)} chunks for BM25")
            
            # Tokenize all chunks
            self._tokenized_corpus = [
                self._tokenize(chunk.text) for chunk in chunks
            ]
            self._chunks = chunks
            
            # Create BM25 index
            self._bm25 = BM25Okapi(self._tokenized_corpus)
            
            logger.info("BM25 index created successfully")
            
        except Exception as e:
            raise RetrievalError(
                f"Failed to create BM25 index: {str(e)}",
                {"num_chunks": len(chunks), "error": str(e)}
            )
    
    def add_chunks(self, chunks: List[Chunk]) -> None:
        """
        Add chunks to existing index (rebuilds index).
        
        Args:
            chunks: New chunks to add
        """
        all_chunks = self._chunks + chunks
        self.index(all_chunks)
    
    def search(self, query: str, top_k: int = 10, user_id: Optional[str] = None) -> List[RetrievalResult]:
        """
        Search using BM25.

        Args:
            query: Search query
            top_k: Number of results
            user_id: Optional user ID for multi-user isolation. If provided, only returns
                     results belonging to this user.

        Returns:
            List of RetrievalResult
        """
        if self._bm25 is None:
            logger.warning("BM25 index not initialized")
            return []

        try:
            # Tokenize query
            query_tokens = self._tokenize(query)

            if not query_tokens:
                return []

            # Get scores
            scores = self._bm25.get_scores(query_tokens)

            # Fetch extra results to account for user_id filtering
            fetch_k = top_k * 3 if user_id else top_k

            # Get top-k indices
            top_indices = sorted(
                range(len(scores)),
                key=lambda i: scores[i],
                reverse=True
            )[:fetch_k]

            # Build results with user_id filtering
            results = []
            for idx in top_indices:
                if scores[idx] > 0:  # Only include if there's some match
                    chunk = self._chunks[idx]

                    # MULTI-USER: Filter by user_id if specified
                    if user_id:
                        chunk_user_id = chunk.metadata.get("user_id") if chunk.metadata else None
                        # Skip if user_id doesn't match (allow NULL for legacy shared data)
                        if chunk_user_id is not None and chunk_user_id != user_id:
                            continue

                    results.append(RetrievalResult(
                        chunk=chunk,
                        score=float(scores[idx]),
                        source="bm25"
                    ))

                    # Stop once we have enough results
                    if len(results) >= top_k:
                        break

            if user_id:
                logger.debug(f"[BM25] User isolation: returned {len(results)} results for user_id={user_id}")

            return results

        except Exception as e:
            raise RetrievalError(
                f"BM25 search failed: {str(e)}",
                {"query": query, "error": str(e)}
            )
    
    def save(self) -> None:
        """Save index and metadata sidecar to disk."""
        if self._bm25 is None:
            logger.warning("[BM25] No index to save")
            return

        try:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "bm25": self._bm25,
                "chunks": self._chunks,
                "tokenized_corpus": self._tokenized_corpus
            }

            with open(self.index_path, 'wb') as f:
                pickle.dump(data, f)

            # Write metadata sidecar
            self._metadata = {
                "build_timestamp": datetime.now(timezone.utc).isoformat(),
                "chunk_count": len(self._chunks),
                "index_path": str(self.index_path),
            }
            self._save_metadata()

            logger.info(
                f"[BM25] Index saved: {self.index_path} "
                f"({len(self._chunks)} chunks, metadata sidecar written)"
            )

        except Exception as e:
            logger.error(f"[BM25] Failed to save index: {e}")
    
    def load(self) -> bool:
        """
        Load index from disk with staleness check.

        Also loads the metadata sidecar to determine if the index is fresh.

        Returns:
            True if loaded successfully
        """
        if not self.index_path.exists():
            logger.info("[BM25] No existing index found — will operate in semantic-only mode")
            return False

        try:
            with open(self.index_path, 'rb') as f:
                data = pickle.load(f)

            self._bm25 = data["bm25"]
            self._chunks = data["chunks"]
            self._tokenized_corpus = data["tokenized_corpus"]

            # Load metadata sidecar
            self._load_metadata()

            build_ts = self._metadata.get("build_timestamp", "unknown")
            chunk_count = self._metadata.get("chunk_count", len(self._chunks))

            logger.info(
                f"[BM25] Loaded index: {len(self._chunks)} chunks "
                f"(built at {build_ts}, metadata reports {chunk_count} chunks)"
            )
            return True

        except Exception as e:
            logger.error(f"[BM25] Failed to load index: {e}")
            return False

    # ─────────────────────────────────────────────────────────────
    # Metadata sidecar management
    # ─────────────────────────────────────────────────────────────
    def _save_metadata(self) -> None:
        """Write metadata sidecar JSON."""
        try:
            with open(self._metadata_path, 'w', encoding='utf-8') as f:
                json.dump(self._metadata, f, indent=2)
        except Exception as e:
            logger.warning(f"[BM25] Failed to write metadata sidecar: {e}")

    def _load_metadata(self) -> None:
        """Read metadata sidecar JSON."""
        if self._metadata_path.exists():
            try:
                with open(self._metadata_path, 'r', encoding='utf-8') as f:
                    self._metadata = json.load(f)
            except Exception as e:
                logger.warning(f"[BM25] Failed to read metadata sidecar: {e}")
                self._metadata = {}
        else:
            self._metadata = {}

    def get_metadata(self) -> Dict:
        """Get current metadata dict."""
        if not self._metadata:
            self._load_metadata()
        return self._metadata.copy()

    # ─────────────────────────────────────────────────────────────
    # Lifecycle: staleness detection & rebuild
    # ─────────────────────────────────────────────────────────────
    def is_stale(self, qdrant_point_count: int) -> bool:
        """
        Check if the BM25 index is stale relative to Qdrant's point count.

        The index is stale if:
          - No metadata sidecar exists (was never built with sidecar)
          - chunk_count in metadata differs from qdrant_point_count by > 5%

        Args:
            qdrant_point_count: current Qdrant collection point count

        Returns:
            True if stale and should be rebuilt
        """
        meta = self.get_metadata()
        last_count = meta.get("chunk_count", 0)

        if last_count == 0:
            logger.info(
                "[BM25-LIFECYCLE] Index has no metadata — considered STALE "
                "(never built with lifecycle tracking)"
            )
            return True

        if qdrant_point_count == 0:
            logger.info("[BM25-LIFECYCLE] Qdrant has 0 points — index not stale")
            return False

        drift = abs(qdrant_point_count - last_count) / max(last_count, 1)
        is_stale = drift > BM25_STALENESS_THRESHOLD

        if is_stale:
            logger.info(
                f"[BM25-LIFECYCLE] Index is STALE: "
                f"qdrant={qdrant_point_count:,} vs index={last_count:,} "
                f"(drift={drift:.1%} > {BM25_STALENESS_THRESHOLD:.0%} threshold)"
            )
        else:
            logger.info(
                f"[BM25-LIFECYCLE] Index is FRESH: "
                f"qdrant={qdrant_point_count:,} vs index={last_count:,} "
                f"(drift={drift:.1%} ≤ {BM25_STALENESS_THRESHOLD:.0%} threshold)"
            )
        return is_stale

    def rebuild_from_qdrant(
        self,
        qdrant_client,
        collection_name: str,
        scroll_batch_size: int = 1000,
    ) -> int:
        """
        Rebuild the BM25 index by scrolling all text payloads from Qdrant.

        This is a NON-BLOCKING operation when run in a background thread.
        While rebuilding, the old (stale) index is still available for queries.

        Args:
            qdrant_client:     Qdrant client instance
            collection_name:   collection to read from
            scroll_batch_size: batch size for scroll API

        Returns:
            Number of chunks indexed
        """
        import time
        start = time.time()

        logger.info(
            f"[BM25-REBUILD] Starting full rebuild from Qdrant collection "
            f"'{collection_name}' (batch_size={scroll_batch_size})..."
        )

        chunks = []
        offset = None
        page = 0

        while True:
            # Scroll through all points
            results, next_offset = qdrant_client.scroll(
                collection_name=collection_name,
                limit=scroll_batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )

            for point in results:
                payload = point.payload or {}
                text = payload.get("text", "")
                if not text:
                    continue

                chunk = Chunk(
                    chunk_id=str(point.id),
                    text=text,
                    doi=payload.get("doi", ""),
                    section=payload.get("section", ""),
                    chunk_index=payload.get("chunk_index", 0),
                    metadata=payload.get("metadata", {}),
                )
                chunks.append(chunk)

            page += 1
            if page % 10 == 0:
                logger.info(
                    f"[BM25-REBUILD] Progress: scrolled {len(chunks):,} chunks "
                    f"({page} pages)..."
                )

            if next_offset is None:
                break
            offset = next_offset

        if not chunks:
            logger.warning(
                "[BM25-REBUILD] No text payloads found in Qdrant — "
                "BM25 index will be empty"
            )
            return 0

        # Rebuild index
        self.index(chunks)
        self.save()

        elapsed = time.time() - start
        logger.info(
            f"[BM25-REBUILD] ✅ Complete: {len(chunks):,} chunks indexed "
            f"in {elapsed:.1f}s. Index saved to {self.index_path}"
        )
        return len(chunks)


def create_bm25_index(
    index_path: str = "data/bm25_index.pkl",
    remove_stopwords: bool = True,
    tokenizer_type: str = "word",
    vector_store: Any = None,
    use_tantivy: bool = False
) -> KeywordIndex:
    """
    Factory to create BM25 index.

    Args:
        index_path: Path to save/load index
        remove_stopwords: Whether to remove stop words
        tokenizer_type: Tokenization strategy
        vector_store: Vector store instance (needed for Tantivy hydration)
        use_tantivy: If True, use Tantivy-based index
    """
    if use_tantivy:
        try:
            import os
            
            from .bm25_tantivy import TantivyBM25Index
            # Handle path logic:
            # 1. If path is a file (legacy .pkl), switch to directory
            # 2. If path doesn't exist, append .tantivy
            # 3. If path exists and is a dir, use it as is
            path_obj = Path(index_path)
            
            if index_path.endswith(".pkl"):
                 index_path = str(path_obj.with_suffix(".tantivy"))
            elif not path_obj.exists() and not index_path.endswith(".tantivy") and not index_path.endswith("_tantivy"):
                 index_path = f"{index_path}.tantivy"
            
            # (If it exists, we assume the user knows what they are doing, even if no extension)
            
            bm25 = TantivyBM25Index(
                index_path=index_path,
                vector_store=vector_store
            )

            # Log index status (no auto-rebuild - handled by pipeline's BM25Worker)
            try:
                searcher = bm25.tantivy_index.searcher()
                doc_count = searcher.num_docs
                if doc_count > 0:
                    logger.info(f"[BM25] Index loaded with {doc_count} documents")
                else:
                    logger.info("[BM25] Index is empty - will be populated by pipeline's BM25Worker")
            except Exception as e:
                logger.warning(f"[BM25] Failed to check index status: {e}")

            return bm25
            
        except ImportError:
            logger.warning("Tantivy requested but not installed. Falling back to rank_bm25.")
        except Exception as e:
             logger.error(f"Failed to create Tantivy index: {e}. Falling back to rank_bm25.")

    return BM25Index(
        index_path=index_path,
        remove_stopwords=remove_stopwords,
        tokenizer_type=tokenizer_type
    )
