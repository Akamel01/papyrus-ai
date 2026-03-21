
import os
import shutil
import logging
from typing import List, Dict, Any, Optional
import tantivy
from qdrant_client import QdrantClient

from src.core.interfaces import RetrievalResult, Chunk, KeywordIndex

logger = logging.getLogger(__name__)

class TantivyBM25Index(KeywordIndex):
    """
    Disk-backed BM25 index using Tantivy (Rust).
    Replaces the memory-bound rank_bm25 implementation.
    
    If vector_store is provided, search results will be hydrated 
    with full payload from Qdrant.
    """
    
    def __init__(self, index_path: str = "data/bm25_index_tantivy", vector_store: Any = None):
        self.index_path = index_path
        self.vector_store = vector_store
        self.schema = self._build_schema()
        self.tantivy_index = self._load_or_create_index()
        
    def _build_schema(self):
        schema_builder = tantivy.SchemaBuilder()
        # ID: Stored so we can retrieve it
        schema_builder.add_text_field("id", stored=True)
        # Text: Indexed for search, NOT stored (we use Qdrant for storage)
        schema_builder.add_text_field("text", stored=False, tokenizer_name="en_stem")
        return schema_builder.build()
        
    def _load_or_create_index(self):
        if not os.path.exists(self.index_path):
            os.makedirs(self.index_path, exist_ok=True)
            return tantivy.Index(self.schema, path=self.index_path)
        return tantivy.Index(self.schema, path=self.index_path) # Open existing

    def index(self, chunks: List[Chunk]) -> None:
        """
        Index a list of chunks.
        
        Args:
            chunks: List of chunks to index
        """
        if not chunks:
            return
            
        logger.info(f"[TANTIVY] Indexing {len(chunks)} chunks...")
        writer = self.tantivy_index.writer()
        
        count = 0
        for chunk in chunks:
            if not chunk.text.strip():
                continue
                
            try:
                # If we have a vector store, we don't strictly need to store text here,
                # but if we are using this method, we might not have Qdrant backing.
                # However, our schema says text is NOT stored.
                # So this index is only useful for ID retrieval.
                doc_dict = {"id": str(chunk.chunk_id), "text": chunk.text}
                writer.add_document(tantivy.Document.from_dict(doc_dict, self.schema))
                count += 1
            except Exception as e:
                logger.warning(f"Failed to add chunk {chunk.chunk_id}: {e}")
                
        writer.commit()
        logger.info(f"[TANTIVY] Committed {count} chunks.")

    def build_from_qdrant(self, client: QdrantClient, collection_name: str, batch_size: int = 1000, heap_size_mb: int = 128, commit_interval: int = 20000, num_threads: int = 0, resume: bool = False):
        """Streaming build from Qdrant."""
        import json
        state_file = os.path.join(self.index_path, "build_state.json")
        
        logger.info(f"[TANTIVY-BUILD] Starting build from Qdrant 'collection={collection_name}' "
                    f"(batch={batch_size}, heap={heap_size_mb}MB, commit={commit_interval}, threads={num_threads}, resume={resume})...")
        
        offset = None
        count = 0
        
        # Optimize writers: if resuming, we must open existing index
        if resume and os.path.exists(self.index_path) and os.path.exists(state_file):
            logger.info(f"[TANTIVY-BUILD] Resuming from existing index at '{self.index_path}'...")
            self.tantivy_index = tantivy.Index(self.schema, path=self.index_path)
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                    offset = state.get("offset")
                    count = state.get("count", 0)
                    logger.info(f"[TANTIVY-BUILD] Resumed state: offset={offset}, count={count}")
            except Exception as e:
                logger.warning(f"[TANTIVY-BUILD] Failed to read state file: {e}. Starting from scratch.")
                offset = None
                count = 0
        else:
            # Reset index if rebuilding
            if os.path.exists(self.index_path):
                logger.info(f"[TANTIVY-BUILD] Releasing index handle for cleanup: {self.index_path}")
                # Release existing index handle and trigger GC to help on Windows
                self.tantivy_index = None
                import gc
                gc.collect()
                
                try:
                    shutil.rmtree(self.index_path)
                except Exception as e:
                    logger.error(f"[TANTIVY-BUILD] CRITICAL: Failed to delete index directory: {e}")
                    logger.error("              -> This is usually caused by another process (Streamlit) holding a lock.")
                    logger.error("              -> To perform a full rebuild, please STOP the Streamlit app first.")
                    raise OSError(f"Directory locked by another process: {self.index_path}") from e
                    
            os.makedirs(self.index_path, exist_ok=True)
            self.tantivy_index = tantivy.Index(self.schema, path=self.index_path)

        # Configurable heap size (in bytes) & threads
        writer = self.tantivy_index.writer(heap_size=heap_size_mb * 1024 * 1024, num_threads=num_threads)
        
        while True:
            # Explicit garbage collection if memory is tight?
            # For now rely on smaller batch size
            results, next_offset = client.scroll(
                collection_name=collection_name,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            
            if not results:
                break
                
            for point in results:
                payload = point.payload or {}
                # Extract text fields
                text_parts = []
                if "title" in payload: text_parts.append(str(payload["title"]))
                if "abstract" in payload: text_parts.append(str(payload["abstract"]))
                if "text" in payload: text_parts.append(str(payload["text"]))
                
                full_text = " ".join(text_parts)
                
                # Add to index
                if full_text.strip():
                     try:
                         doc_dict = {"id": str(point.id), "text": full_text}
                         writer.add_document(tantivy.Document.from_dict(doc_dict, self.schema))
                         count += 1
                     except Exception as e:
                         # Log error but don't crash whole build for one doc
                         logger.warning(f"Failed to add doc {point.id}: {e}")
            
            # Progress logging
            if count % 10000 == 0:
                logger.info(f"[TANTIVY-BUILD] Indexed {count} documents...")
                
            # Configurable commit interval
            if count > 0 and count % commit_interval == 0:
                 logger.info(f"[TANTIVY-BUILD] Committing at {count}...")
                 writer.commit()
                 # Save state
                 with open(state_file, 'w') as f:
                     json.dump({"offset": next_offset, "count": count}, f)
            
            if next_offset is None:
                break
            offset = next_offset
            
        logger.info(f"[TANTIVY-BUILD] Final Commit...")
        writer.commit()
        # Clean up state file on success
        if os.path.exists(state_file):
            os.remove(state_file)
            
        logger.info(f"[TANTIVY-BUILD] ✅ Build complete. Indexed {count} documents.")
        return count

    def search(self, query: str, top_k: int = 10, user_id: Optional[str] = None) -> List[RetrievalResult]:
        """Search the index.

        Args:
            query: Search query
            top_k: Number of results to return
            user_id: Optional user ID for multi-user isolation. If provided, only returns
                     results belonging to this user.
        """
        # Ensure index is up to date (reload not always needed but safer for concurrent writes)
        self.tantivy_index.reload()
        searcher = self.tantivy_index.searcher()
        query_parser = self.tantivy_index.parse_query(query, ["text"])

        # Fetch extra results to account for user_id filtering
        fetch_k = top_k * 3 if user_id else top_k

        try:
            results = searcher.search(query_parser, fetch_k).hits
        except Exception as e:
            logger.warning(f"Tantivy search error for '{query}': {e}")
            return []

        # Extract IDs
        doc_ids = []
        scores = {}
        for score, address in results:
            doc = searcher.doc(address)
            doc_id = doc["id"][0]
            doc_ids.append(doc_id)
            scores[doc_id] = score

        if not doc_ids:
            return []

        # Hydrate from Qdrant if possible
        retrieved_results = []

        if self.vector_store:
            try:
                # Assuming QdrantVectorStore
                client = self.vector_store._get_client()
                collection = self.vector_store.collection_name

                points = client.retrieve(
                    collection_name=collection,
                    ids=doc_ids,
                    with_payload=True,
                    with_vectors=False
                )

                # Convert to RetrievalResult with user_id filtering
                for point in points:
                    payload = point.payload or {}

                    # MULTI-USER: Filter by user_id if specified
                    if user_id:
                        point_user_id = payload.get("user_id")
                        # Skip if user_id doesn't match (allow NULL for legacy shared data)
                        if point_user_id is not None and point_user_id != user_id:
                            logger.debug(f"[BM25] Filtering out chunk {point.id} - belongs to user {point_user_id}")
                            continue

                    # Metadata enrichment (same as vector_store.py)
                    enriched_metadata = payload.get("metadata", {}).copy()
                    enrichment_fields = [
                        "citation_str", "title", "authors", "year", "venue",
                        "volume", "issue", "first_page", "last_page", "apa_reference"
                    ]
                    for key in enrichment_fields:
                        if key in payload:
                            enriched_metadata[key] = payload[key]

                    chunk = Chunk(
                        chunk_id=point.id,
                        text=payload.get("text", ""),
                        doi=payload.get("doi", ""),
                        section=payload.get("section", ""),
                        chunk_index=payload.get("chunk_index", 0),
                        metadata=enriched_metadata,
                    )

                    retrieved_results.append(RetrievalResult(
                        chunk=chunk,
                        score=scores.get(point.id, 0.0),
                        source="bm25"
                    ))

                # Sort by score again (retrieve might not preserve order)
                retrieved_results.sort(key=lambda x: x.score, reverse=True)

                # Trim to top_k after filtering
                retrieved_results = retrieved_results[:top_k]

                if user_id:
                    logger.debug(f"[BM25] User isolation: returned {len(retrieved_results)} results for user_id={user_id}")

            except Exception as e:
                logger.error(f"Failed to hydrate BM25 results from Qdrant: {e}")
                # Fallback to hydration failure? Or stub?
                return []
        else:
            # Return stubs if no vector_store (HybridSearch will likely crash or log error)
            # But constructing Chunk requires fields.
            for doc_id in doc_ids:
                 chunk = Chunk(
                     chunk_id=doc_id,
                     text="",
                     doi="",
                 )
                 retrieved_results.append(RetrievalResult(
                     chunk=chunk,
                     score=scores.get(doc_id, 0.0),
                     source="bm25_stub"
                 ))

        return retrieved_results
        
    def is_stale(self, qdrant_point_count: int) -> bool:
        """
        Check if the BM25 index is stale relative to Qdrant's point count.
        
        Drift > 5% triggers rebuild.
        """
        if qdrant_point_count == 0:
            return False
            
        try:
            searcher = self.tantivy_index.searcher()
            doc_count = searcher.num_docs
            
            # Handle callable if needed (though num_docs is property in newer tantivy-py)
            if callable(doc_count):
                doc_count = doc_count()
                
            drift = abs(qdrant_point_count - doc_count) / max(doc_count, 1)
            is_stale = drift > 0.05 # 5% threshold
            
            if is_stale:
                logger.warning(
                    f"[BM25-LIFECYCLE] Index is STALE: "
                    f"qdrant={qdrant_point_count:,} vs index={doc_count:,} "
                    f"(drift={drift:.1%})"
                )
            else:
                 logger.info(
                    f"[BM25-LIFECYCLE] Index is FRESH: "
                    f"qdrant={qdrant_point_count:,} vs index={doc_count:,}"
                )
                
            return is_stale
            
        except Exception as e:
            logger.warning(f"Failed to check staleness: {e}")
            return True # Assume stale on error
