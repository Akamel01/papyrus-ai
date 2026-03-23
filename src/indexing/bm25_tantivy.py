
import os
import shutil
import logging
import json
import time
from typing import List, Dict, Any, Optional, Set
import tantivy
from qdrant_client import QdrantClient

from src.core.interfaces import RetrievalResult, Chunk, KeywordIndex

logger = logging.getLogger(__name__)

# File to track indexed IDs for incremental updates
INDEXED_IDS_FILE = "indexed_ids.json"
# Maximum IDs to store in memory before switching to file-based tracking
MAX_MEMORY_IDS = 100_000

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

    def _get_indexed_ids_path(self) -> str:
        """Get path to the indexed IDs tracking file."""
        return os.path.join(self.index_path, INDEXED_IDS_FILE)

    def _load_indexed_ids(self) -> Set[str]:
        """Load the set of already-indexed IDs from disk."""
        ids_path = self._get_indexed_ids_path()
        if os.path.exists(ids_path):
            try:
                with open(ids_path, 'r') as f:
                    data = json.load(f)
                    return set(data.get("ids", []))
            except Exception as e:
                logger.warning(f"[TANTIVY] Failed to load indexed IDs: {e}")
        return set()

    def _save_indexed_ids(self, ids: Set[str]) -> None:
        """Save the set of indexed IDs to disk."""
        ids_path = self._get_indexed_ids_path()
        try:
            with open(ids_path, 'w') as f:
                json.dump({"ids": list(ids), "updated_at": time.time()}, f)
        except Exception as e:
            logger.warning(f"[TANTIVY] Failed to save indexed IDs: {e}")

    def _append_indexed_ids(self, new_ids: Set[str]) -> None:
        """Append new IDs to the tracking file (for large datasets)."""
        existing = self._load_indexed_ids()
        existing.update(new_ids)
        self._save_indexed_ids(existing)

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

        # Initialize tracking file for future incremental updates
        logger.info(f"[TANTIVY-BUILD] Initializing tracking file for incremental updates...")
        self._rebuild_tracking_from_index()

        logger.info(f"[TANTIVY-BUILD] ✅ Build complete. Indexed {count} documents.")
        return count

    def incremental_update(self, client: QdrantClient, collection_name: str, batch_size: int = 1000, heap_size_mb: int = 128) -> int:
        """
        Incrementally update the BM25 index with only NEW vectors from Qdrant.

        This is much faster than a full rebuild for large datasets (10M+ vectors).
        It tracks which IDs have been indexed and only processes new ones.

        Args:
            client: QdrantClient instance
            collection_name: Qdrant collection to sync from
            batch_size: Number of vectors to fetch per batch
            heap_size_mb: Tantivy writer heap size

        Returns:
            Number of new documents indexed
        """
        logger.info(f"[TANTIVY-INCREMENTAL] Starting incremental update from '{collection_name}'...")
        start_time = time.time()

        # Load existing indexed IDs
        indexed_ids = self._load_indexed_ids()
        initial_count = len(indexed_ids)
        logger.info(f"[TANTIVY-INCREMENTAL] Found {initial_count:,} already-indexed IDs")

        # Get total count from Qdrant
        try:
            collection_info = client.get_collection(collection_name)
            qdrant_count = collection_info.points_count
            logger.info(f"[TANTIVY-INCREMENTAL] Qdrant has {qdrant_count:,} vectors")
        except Exception as e:
            logger.error(f"[TANTIVY-INCREMENTAL] Failed to get collection info: {e}")
            return 0

        # If counts match, no update needed
        if initial_count >= qdrant_count:
            logger.info(f"[TANTIVY-INCREMENTAL] Index is up-to-date, no new vectors to index")
            return 0

        # Scroll through Qdrant and find new IDs
        new_count = 0
        offset = None
        writer = self.tantivy_index.writer(heap_size=heap_size_mb * 1024 * 1024)
        new_ids_batch: Set[str] = set()

        while True:
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
                point_id = str(point.id)

                # Skip if already indexed
                if point_id in indexed_ids:
                    continue

                payload = point.payload or {}

                # Extract text fields
                text_parts = []
                if "title" in payload: text_parts.append(str(payload["title"]))
                if "abstract" in payload: text_parts.append(str(payload["abstract"]))
                if "text" in payload: text_parts.append(str(payload["text"]))

                full_text = " ".join(text_parts)

                if full_text.strip():
                    try:
                        doc_dict = {"id": point_id, "text": full_text}
                        writer.add_document(tantivy.Document.from_dict(doc_dict, self.schema))
                        new_ids_batch.add(point_id)
                        new_count += 1
                    except Exception as e:
                        logger.warning(f"[TANTIVY-INCREMENTAL] Failed to add doc {point_id}: {e}")

            # Progress logging every 10k new docs
            if new_count > 0 and new_count % 10000 == 0:
                logger.info(f"[TANTIVY-INCREMENTAL] Indexed {new_count:,} new documents...")

            # Commit and save state every 50k new docs
            if new_count > 0 and new_count % 50000 == 0:
                logger.info(f"[TANTIVY-INCREMENTAL] Committing at {new_count:,}...")
                writer.commit()
                indexed_ids.update(new_ids_batch)
                self._save_indexed_ids(indexed_ids)
                new_ids_batch.clear()
                writer = self.tantivy_index.writer(heap_size=heap_size_mb * 1024 * 1024)

            if next_offset is None:
                break
            offset = next_offset

        # Final commit
        if new_count > 0:
            logger.info(f"[TANTIVY-INCREMENTAL] Final commit...")
            writer.commit()
            indexed_ids.update(new_ids_batch)
            self._save_indexed_ids(indexed_ids)

        elapsed = time.time() - start_time
        rate = new_count / elapsed if elapsed > 0 else 0
        logger.info(f"[TANTIVY-INCREMENTAL] ✅ Indexed {new_count:,} new documents in {elapsed:.1f}s ({rate:.0f} docs/sec)")

        return new_count

    def sync_with_qdrant(self, client: QdrantClient, collection_name: str, force_rebuild: bool = False, **kwargs) -> int:
        """
        Smart sync: uses incremental update if possible, full rebuild if necessary.

        Args:
            client: QdrantClient instance
            collection_name: Qdrant collection to sync from
            force_rebuild: Force a full rebuild even if incremental is possible
            **kwargs: Additional args passed to build_from_qdrant or incremental_update

        Returns:
            Number of documents indexed (new or total depending on mode)
        """
        # Check if we have an existing index with tracking
        indexed_ids = self._load_indexed_ids()
        has_tracking = len(indexed_ids) > 0

        # Get Qdrant count
        try:
            collection_info = client.get_collection(collection_name)
            qdrant_count = collection_info.points_count
        except Exception as e:
            logger.error(f"[TANTIVY-SYNC] Failed to get collection info: {e}")
            return 0

        # Decide: incremental or full rebuild
        if force_rebuild:
            logger.info(f"[TANTIVY-SYNC] Force rebuild requested")
            # Clear tracking file
            ids_path = self._get_indexed_ids_path()
            if os.path.exists(ids_path):
                os.remove(ids_path)
            return self.build_from_qdrant(client, collection_name, **kwargs)

        if not has_tracking:
            # No tracking file = first build or corrupted state
            # Check if index has documents
            try:
                searcher = self.tantivy_index.searcher()
                doc_count = searcher.num_docs
                if callable(doc_count):
                    doc_count = doc_count()
            except:
                doc_count = 0

            if doc_count == 0:
                # Empty index, do full build
                logger.info(f"[TANTIVY-SYNC] Empty index, performing full build...")
                count = self.build_from_qdrant(client, collection_name, **kwargs)
                # Initialize tracking after successful build
                self._rebuild_tracking_from_index()
                return count
            else:
                # Index has docs but no tracking - rebuild tracking
                logger.info(f"[TANTIVY-SYNC] Index has {doc_count:,} docs but no tracking. Rebuilding tracking file...")
                self._rebuild_tracking_from_index()
                indexed_ids = self._load_indexed_ids()

        # Use incremental update
        return self.incremental_update(client, collection_name, **kwargs)

    def _rebuild_tracking_from_index(self) -> None:
        """Rebuild the tracking file by scanning all documents in the index."""
        logger.info(f"[TANTIVY] Rebuilding tracking file from index...")
        try:
            self.tantivy_index.reload()
            searcher = self.tantivy_index.searcher()

            # Use a wildcard search to get all documents
            # This is a bit hacky but Tantivy doesn't have a native "get all" method
            query_parser = self.tantivy_index.parse_query("*", ["text"])

            doc_count = searcher.num_docs
            if callable(doc_count):
                doc_count = doc_count()

            # Fetch all document IDs
            indexed_ids: Set[str] = set()
            try:
                results = searcher.search(query_parser, doc_count).hits
                for _, address in results:
                    doc = searcher.doc(address)
                    doc_id = doc["id"][0]
                    indexed_ids.add(doc_id)
            except Exception as e:
                logger.warning(f"[TANTIVY] Wildcard search failed: {e}. Using empty tracking.")
                indexed_ids = set()

            self._save_indexed_ids(indexed_ids)
            logger.info(f"[TANTIVY] Rebuilt tracking with {len(indexed_ids):,} IDs")

        except Exception as e:
            logger.error(f"[TANTIVY] Failed to rebuild tracking: {e}")

    def search(
        self,
        query: str,
        top_k: int = 10,
        user_id: Optional[str] = None,
        knowledge_source: str = "both"
    ) -> List[RetrievalResult]:
        """Search the index.

        Args:
            query: Search query
            top_k: Number of results to return
            user_id: Optional user ID for multi-user isolation. Required for user_only and both modes.
            knowledge_source: Which knowledge sources to search:
                - "shared_only": Only shared KB (user_id is NULL)
                - "user_only": Only user's documents (requires user_id)
                - "both": User's docs + shared KB (default)
        """
        # Ensure index is up to date (reload not always needed but safer for concurrent writes)
        self.tantivy_index.reload()
        searcher = self.tantivy_index.searcher()
        query_parser = self.tantivy_index.parse_query(query, ["text"])

        # Fetch extra results to account for filtering
        needs_filtering = knowledge_source != "shared_only" or user_id is not None
        fetch_k = top_k * 3 if needs_filtering else top_k

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

                # Convert to RetrievalResult with knowledge_source filtering
                for point in points:
                    payload = point.payload or {}
                    point_user_id = payload.get("user_id")

                    # Apply knowledge_source filtering
                    if knowledge_source == "shared_only":
                        # Only include shared KB (user_id is NULL)
                        if point_user_id is not None:
                            continue
                    elif knowledge_source == "user_only":
                        # Only include user's documents
                        if not user_id or point_user_id != user_id:
                            continue
                    elif knowledge_source == "both":
                        # Include user's docs + shared KB
                        if point_user_id is not None and point_user_id != user_id:
                            # Skip docs belonging to OTHER users
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
        status = self.get_sync_status(qdrant_point_count)
        return status.get("is_stale", True)

    def get_sync_status(self, qdrant_point_count: int) -> Dict[str, Any]:
        """
        Get detailed sync status comparing BM25 index to Qdrant.

        Returns:
            Dict with keys:
                - is_stale: bool - True if index needs update
                - needs_incremental: bool - True if incremental update is sufficient
                - needs_full_rebuild: bool - True if full rebuild is needed
                - index_count: int - Number of docs in BM25 index
                - qdrant_count: int - Number of vectors in Qdrant
                - tracked_count: int - Number of IDs in tracking file
                - missing_count: int - Estimated new vectors to index
                - drift_pct: float - Drift percentage
        """
        result = {
            "is_stale": False,
            "needs_incremental": False,
            "needs_full_rebuild": False,
            "index_count": 0,
            "qdrant_count": qdrant_point_count,
            "tracked_count": 0,
            "missing_count": 0,
            "drift_pct": 0.0,
        }

        if qdrant_point_count == 0:
            return result

        try:
            searcher = self.tantivy_index.searcher()
            doc_count = searcher.num_docs

            # Handle callable if needed (though num_docs is property in newer tantivy-py)
            if callable(doc_count):
                doc_count = doc_count()

            result["index_count"] = doc_count

            # Check tracking file
            indexed_ids = self._load_indexed_ids()
            result["tracked_count"] = len(indexed_ids)

            # Calculate drift
            drift = abs(qdrant_point_count - doc_count) / max(doc_count, 1) if doc_count > 0 else 1.0
            result["drift_pct"] = round(drift * 100, 1)

            # Determine if stale (>5% drift)
            is_stale = drift > 0.05
            result["is_stale"] = is_stale

            if is_stale:
                # Calculate missing count
                missing = max(0, qdrant_point_count - doc_count)
                result["missing_count"] = missing

                # Decide: incremental vs full rebuild
                # Use incremental if:
                # 1. We have a valid tracking file
                # 2. Missing count is < 50% of total (otherwise full rebuild is more efficient)
                has_valid_tracking = result["tracked_count"] > 0 and abs(result["tracked_count"] - doc_count) < 1000
                missing_ratio = missing / max(qdrant_point_count, 1)

                if has_valid_tracking and missing_ratio < 0.5:
                    result["needs_incremental"] = True
                    logger.info(
                        f"[BM25-LIFECYCLE] Index is STALE (incremental update recommended): "
                        f"qdrant={qdrant_point_count:,} vs index={doc_count:,} "
                        f"(missing={missing:,}, drift={drift:.1%})"
                    )
                else:
                    result["needs_full_rebuild"] = True
                    logger.warning(
                        f"[BM25-LIFECYCLE] Index is STALE (full rebuild recommended): "
                        f"qdrant={qdrant_point_count:,} vs index={doc_count:,} "
                        f"(missing={missing:,}, drift={drift:.1%}, tracked={result['tracked_count']:,})"
                    )
            else:
                logger.info(
                    f"[BM25-LIFECYCLE] Index is FRESH: "
                    f"qdrant={qdrant_point_count:,} vs index={doc_count:,}"
                )

            return result

        except Exception as e:
            logger.warning(f"Failed to check staleness: {e}")
            result["is_stale"] = True
            result["needs_full_rebuild"] = True
            return result

    def delete_by_ids(self, chunk_ids: List[str]) -> int:
        """
        Delete documents from the BM25 index by their chunk IDs.

        Args:
            chunk_ids: List of chunk IDs to delete

        Returns:
            Number of documents deleted
        """
        if not chunk_ids:
            return 0

        logger.info(f"[TANTIVY] Deleting {len(chunk_ids)} chunks from BM25 index...")

        try:
            writer = self.tantivy_index.writer()
            deleted = 0

            for chunk_id in chunk_ids:
                try:
                    # Delete by term match on the "id" field
                    writer.delete_documents("id", chunk_id)
                    deleted += 1
                except Exception as e:
                    logger.warning(f"[TANTIVY] Failed to delete chunk {chunk_id}: {e}")

            writer.commit()
            self.tantivy_index.reload()

            # Update tracking file (remove deleted IDs)
            indexed_ids = self._load_indexed_ids()
            for chunk_id in chunk_ids:
                indexed_ids.discard(chunk_id)
            self._save_indexed_ids(indexed_ids)

            logger.info(f"[TANTIVY] Deleted {deleted} chunks from BM25 index")
            return deleted

        except Exception as e:
            logger.error(f"[TANTIVY] Delete operation failed: {e}")
            raise
