"""
SME Research Assistant - Vector Store

Qdrant vector database operations with HNSW, scalar quantization,
and auto-tuned search parameters.
"""

import logging
import time
from typing import List, Dict, Any, Optional
from dataclasses import asdict

from src.core.interfaces import VectorStore, Chunk, RetrievalResult
from src.core.exceptions import VectorStoreError, VectorStoreConnectionError

logger = logging.getLogger(__name__)


class QdrantVectorStore(VectorStore):
    """
    Vector store implementation using Qdrant.
    """
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "sme_papers",
        embedding_dimension: int = 4096,
        location: Optional[str] = None,
        qdrant_batch_size: int = 100,
        timeout: int = 60,
        optimized_params: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize Qdrant vector store.
        
        Args:
            host: Qdrant server host
            port: Qdrant server port
            collection_name: Name of the collection
            embedding_dimension: Dimension of embeddings
            location: Local path or ":memory:" for embedded mode
            qdrant_batch_size: Batch size for upsert operations (default: 100)
            timeout: Client timeout in seconds (default: 60)
            optimized_params: Dict from qdrant_optimizer.compute_optimal_params().
                              If provided, these are used for collection creation
                              and search-time parameters. If None, sensible
                              defaults are used.
        """
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.embedding_dimension = embedding_dimension
        self.location = location
        self.qdrant_batch_size = qdrant_batch_size
        self.timeout = timeout
        self._client = None
        self._upsert_count = 0          # Track cumulative upserts for periodic flush
        self._flush_interval = 250      # Force flush every N points (10 papers × 25 chunks)

        # ── Store optimized parameters (from qdrant_optimizer or defaults) ──
        self._opt = optimized_params or {}
        self._search_hnsw_ef    = self._opt.get("ef_search", 400)
        self._search_oversampling = self._opt.get("oversampling", 2.0)
        self._search_rescore    = self._opt.get("rescore", True)
        self._use_quantization  = self._opt.get("use_quantization", True)

        if self._opt:
            logger.info(
                f"[VECTOR-STORE] ✅ Optimization Params Received:\n"
                f"              • EF Search: {self._search_hnsw_ef}\n"
                f"              • Oversampling: {self._search_oversampling}x\n"
                f"              • Rescoring: {self._search_rescore}\n"
                f"              • Quantization: {'Enabled' if self._use_quantization else 'Disabled'}"
            )
        else:
            logger.info(
                "[VECTOR-STORE] No optimized_params provided — "
                "using defaults (ef_search=400, oversampling=2.0, rescore=True)"
            )
    
    def _get_client(self):
        """Get or create Qdrant client."""
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
                from qdrant_client.http import models
                
                if self.location:
                   logger.info(f"Initializing Embedded Qdrant at: {self.location}")
                   self._client = QdrantClient(path=self.location)
                else:
                   self._client = QdrantClient(host=self.host, port=self.port, timeout=self.timeout)
                
                self._models = models
                
                # Check connection
                self._client.get_collections()
                if self.location:
                    logger.info(f"Connected to Qdrant (Embedded): {self.location}")
                else:
                    logger.info(f"Connected to Qdrant at {self.host}:{self.port}")
                
            except Exception as e:
                loc_info = self.location if self.location else f"{self.host}:{self.port}"
                raise VectorStoreConnectionError(
                    f"Failed to connect to Qdrant: {str(e)}",
                    {"location": loc_info, "error": str(e)}
                )
        
        return self._client
    
    def create_collection(self, recreate: bool = False) -> None:
        """
        Create the collection with optimized HNSW, quantization, and storage config.

        When optimized_params is available (from qdrant_optimizer), the collection
        is created with:
          - HNSW: m, ef_construct, on_disk=False, max_indexing_threads=0
          - Scalar Quantization: int8, quantile=0.99, always_ram=True
          - Vectors on_disk: True (original vectors stored on NVMe, mmap'd)
          - Optimizers: segment_count, max_segment_size, flush_interval
          - Payload on_disk: True

        Args:
            recreate: If True, delete and recreate the collection
        """
        client = self._get_client()

        try:
            collections = client.get_collections().collections
            exists = any(c.name == self.collection_name for c in collections)

            if exists and recreate:
                logger.warning(f"[COLLECTION] Deleting existing collection: {self.collection_name}")
                client.delete_collection(self.collection_name)
                exists = False

            if not exists:
                # ── Build vector params ──
                on_disk_vectors = self._opt.get("on_disk_vectors", True)
                vectors_config = self._models.VectorParams(
                    size=self.embedding_dimension,
                    distance=self._models.Distance.COSINE,
                    on_disk=on_disk_vectors,
                )
                logger.info(
                    f"[COLLECTION] Creating '{self.collection_name}': "
                    f"dim={self.embedding_dimension}, distance=Cosine, "
                    f"on_disk_vectors={on_disk_vectors}"
                )

                # ── Build HNSW config ──
                m            = self._opt.get("m", 32)
                ef_construct = self._opt.get("ef_construct", 128)
                hnsw_on_disk = self._opt.get("hnsw_on_disk", False)
                hnsw_config = self._models.HnswConfigDiff(
                    m=m,
                    ef_construct=ef_construct,
                    full_scan_threshold=self._opt.get("full_scan_threshold", 20000),
                    max_indexing_threads=self._opt.get("max_indexing_threads", 0),
                    on_disk=hnsw_on_disk,
                )
                logger.info(
                    f"[COLLECTION] HNSW config: m={m}, ef_construct={ef_construct}, "
                    f"on_disk={hnsw_on_disk}, max_threads=all-cores"
                )

                # ── Build quantization config (if tier != LUXURY) ──
                quantization_config = None
                if self._opt.get("use_quantization", True):
                    quantile  = self._opt.get("quantile", 0.99)
                    always_ram = self._opt.get("always_ram", True)
                    quantization_config = self._models.ScalarQuantization(
                        scalar=self._models.ScalarQuantizationConfig(
                            type=self._models.ScalarType.INT8,
                            quantile=quantile,
                            always_ram=always_ram,
                        )
                    )
                    logger.info(
                        f"[COLLECTION] Scalar Quantization: type=int8, "
                        f"quantile={quantile}, always_ram={always_ram}"
                    )
                else:
                    logger.info("[COLLECTION] Quantization: DISABLED (LUXURY tier)")

                # ── Build optimizers config ──
                seg_count = self._opt.get("segment_count", 8)
                optimizers_config = self._models.OptimizersConfigDiff(
                    default_segment_number=seg_count,
                    max_segment_size=self._opt.get("max_segment_size", 200000),
                    indexing_threshold=self._opt.get("indexing_threshold", 20000),
                    flush_interval_sec=self._opt.get("flush_interval_sec", 5),
                )
                logger.info(
                    f"[COLLECTION] Optimizers: segments={seg_count}, "
                    f"max_seg_size={self._opt.get('max_segment_size', 200000)}, "
                    f"flush_interval={self._opt.get('flush_interval_sec', 5)}s"
                )

                # ── Create the collection ──
                client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=vectors_config,
                    hnsw_config=hnsw_config,
                    quantization_config=quantization_config,
                    optimizers_config=optimizers_config,
                    on_disk_payload=True,
                )

                # ── Create payload indexes for filtering ──
                client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="doi",
                    field_schema=self._models.PayloadSchemaType.KEYWORD,
                )
                client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="section",
                    field_schema=self._models.PayloadSchemaType.KEYWORD,
                )
                # Multi-user isolation: index user_id for filtered queries
                client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="user_id",
                    field_schema=self._models.PayloadSchemaType.KEYWORD,
                )

                logger.info(
                    f"[COLLECTION] ✅ Creation Success for '{self.collection_name}':\n"
                    f"            -> HNSW: m={m} | ef_construct={ef_construct} | on_disk={hnsw_on_disk}\n"
                    f"            -> Quantization: {'INT8' if quantization_config else 'None'}\n"
                    f"            -> Vectors: {'Disk + RAM' if on_disk_vectors else 'RAM Only'}\n"
                    f"            -> Optimizers: {seg_count} segments"
                )
            else:
                logger.info(
                    f"[COLLECTION] Collection '{self.collection_name}' already exists — "
                    f"using existing config. Run optimizer.validate_config() to check."
                )

        except Exception as e:
            raise VectorStoreError(
                f"Failed to create collection: {str(e)}",
                {"collection": self.collection_name, "error": str(e)}
            )
    
    def upsert(self, chunks: List[Chunk]) -> None:
        """
        Insert or update chunks in the store.
        
        Args:
            chunks: List of chunks with embeddings
        """
        if not chunks:
            logger.warning("[UPSERT-SKIP] No chunks provided - nothing to upsert")
            return
        
        # Diagnostic logging - START
        logger.info(f"[UPSERT-START] Collection={self.collection_name}, Chunks={len(chunks)}")
        
        # Validate embeddings before proceeding
        null_embeddings = sum(1 for c in chunks if c.embedding is None)
        if null_embeddings > 0:
            logger.error(f"[UPSERT-ERROR] {null_embeddings}/{len(chunks)} chunks have NULL embeddings!")
        
        # Sample first chunk for debugging
        first_chunk = chunks[0]
        if first_chunk.embedding:
            logger.info(f"[UPSERT-SAMPLE] First chunk: id={first_chunk.chunk_id}, "
                       f"doi={first_chunk.doi}, embedding_dim={len(first_chunk.embedding)}")
        
        client = self._get_client()
        
        # Ensure collection exists
        self.create_collection()
        
        try:
            points = []
            for chunk in chunks:
                if chunk.embedding is None:
                    raise VectorStoreError(
                        f"Chunk {chunk.chunk_id} has no embedding",
                        {"chunk_id": chunk.chunk_id}
                    )
                
                # VALIDATE ALL chunks for malformed embeddings
                emb = chunk.embedding
                
                if not isinstance(emb, list):
                    logger.error(f"[VECTOR-INVALID] Chunk {chunk.chunk_id}: embedding is {type(emb)}, not list")
                    raise VectorStoreError(f"Chunk {chunk.chunk_id} embedding is not a list", {"type": str(type(emb))})
                
                if len(emb) != self.embedding_dimension:
                    logger.error(f"[VECTOR-INVALID] Chunk {chunk.chunk_id}: len={len(emb)}, expected={self.embedding_dimension}")
                    raise VectorStoreError(f"Chunk {chunk.chunk_id} has wrong dimension", {"dim": len(emb)})
                
                # Check for non-float elements (e.g., nested lists, None, numpy types)
                if len(emb) > 0 and not isinstance(emb[0], (int, float)):
                    logger.error(f"[VECTOR-INVALID] Chunk {chunk.chunk_id}: first element is {type(emb[0])}, sample={emb[:3]}")
                    raise VectorStoreError(f"Chunk {chunk.chunk_id} has non-numeric elements", {"elem_type": str(type(emb[0]))})
                
                # CRITICAL: Convert all values to native Python floats to avoid JSON serialization issues
                # numpy.float16/float32/float64 can cause "VectorStruct" errors in qdrant_client
                vector_data = [float(x) for x in emb]
                
                # Build payload with optional user_id for multi-user isolation
                payload = {
                    "text": chunk.text,
                    "doi": chunk.doi,
                    "section": chunk.section,
                    "chunk_index": chunk.chunk_index,
                    "metadata": chunk.metadata
                }
                # Extract user_id to top-level for efficient filtering
                if chunk.metadata and "user_id" in chunk.metadata:
                    payload["user_id"] = chunk.metadata["user_id"]

                point = self._models.PointStruct(
                    id=chunk.chunk_id,
                    vector=vector_data,
                    payload=payload
                )
                points.append(point)
            
            logger.info(f"[UPSERT-POINTS] Built {len(points)} PointStruct objects")
            
            # Upsert in batches with per-batch logging
            batch_size = self.qdrant_batch_size  # Configurable from acquisition_config.yaml
            total_batches = (len(points) + batch_size - 1) // batch_size
            
            for i in range(0, len(points), batch_size):
                batch = points[i:i + batch_size]
                batch_num = i // batch_size + 1
                
                logger.info(f"[UPSERT-BATCH] Sending batch {batch_num}/{total_batches}, points={len(batch)}")
                
                # Execute upsert with wait=True to guarantee WAL fsync for data integrity
                try:
                    result = client.upsert(
                        collection_name=self.collection_name,
                        points=batch,
                        wait=True  # Blocking: guarantees vectors are safely in WAL before returning
                    )
                    self._upsert_count += len(batch)
                except Exception as upsert_error:
                    # Log diagnostic info and re-raise - stages.py handles VectorStruct recovery
                    logger.error(f"[UPSERT-FAILED] Batch of {len(batch)} failed: {upsert_error}")
                    if batch:
                        p = batch[0]
                        logger.error(f"[UPSERT-FAILED] First point: id={p.id}, vector_len={len(p.vector) if p.vector else 'None'}")
                    raise
                
                # Log Qdrant response if available
                if result:
                    logger.info(f"[UPSERT-RESPONSE] Batch {batch_num}: status={result.status if hasattr(result, 'status') else 'OK'}")
            
            # Final verification - get collection info including optimizer status
            try:
                collection_info = client.get_collection(self.collection_name)
                points_count = collection_info.points_count if hasattr(collection_info, 'points_count') else 'unknown'
                
                # Check optimizer status to verify WAL→Segment flush is happening
                optimizer_status = collection_info.optimizer_status if hasattr(collection_info, 'optimizer_status') else None
                if optimizer_status:
                    status_str = optimizer_status.status if hasattr(optimizer_status, 'status') else str(optimizer_status)
                    logger.info(f"[UPSERT-OPTIMIZER] Optimizer status: {status_str}")
                    if status_str not in ['ok', 'Ok', 'green']:
                        logger.warning(f"[UPSERT-OPTIMIZER] Optimizer not in 'ok' state - segments may be rebuilding")
                
                logger.info(f"[UPSERT-COMPLETE] All {len(chunks)} chunks sent. Collection points_count={points_count}")
            except Exception as e:
                logger.warning(f"[UPSERT-VERIFY] Could not verify collection: {e}")

            # NOTE: Periodic WAL→segment flush is handled by Qdrant's built-in
            # flush_interval_sec (configured at collection creation, default 5s).
            # Do NOT use create_snapshot() for flushing — it copies the entire
            # collection (~29 GB) to tmp/, filling disk and causing OOM.
            
        except Exception as e:
            logger.error(f"[UPSERT-FAILED] Error upserting {len(chunks)} chunks: {e}")
            raise VectorStoreError(
                f"Failed to upsert chunks: {str(e)}",
                {"num_chunks": len(chunks), "error": str(e)}
            )
    
    def force_flush(self) -> bool:
        """
        Force flush WAL to segments by creating a snapshot.
        
        Creating a snapshot forces Qdrant to persist all WAL data to disk
        because the snapshot needs a consistent state.
        
        Returns:
            True if flush was successful, False otherwise.
        """
        client = self._get_client()
        
        try:
            logger.info(f"[FLUSH-START] Creating snapshot to force WAL flush for collection={self.collection_name}")
            
            # Create snapshot - this forces all data to be persisted
            snapshot_info = client.create_snapshot(
                collection_name=self.collection_name,
                wait=True  # Wait for snapshot to complete
            )
            
            logger.info(f"[FLUSH-SNAPSHOT] Snapshot created: {snapshot_info}")
            
            # Verify collection state after flush
            collection_info = client.get_collection(self.collection_name)
            points_count = collection_info.points_count if hasattr(collection_info, 'points_count') else 'unknown'
            optimizer_status = collection_info.optimizer_status if hasattr(collection_info, 'optimizer_status') else None
            
            status_str = 'unknown'
            if optimizer_status:
                status_str = optimizer_status.status if hasattr(optimizer_status, 'status') else str(optimizer_status)
            
            logger.info(f"[FLUSH-COMPLETE] Collection points_count={points_count}, optimizer_status={status_str}")
            
            return True
            
        except Exception as e:
            logger.error(f"[FLUSH-FAILED] Error forcing flush: {e}")
            return False
    
    
    def search(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        search_params: Optional[Dict[str, Any]] = None
    ) -> List[RetrievalResult]:
        """
        Search for similar chunks using optimized HNSW + quantization params.

        Search-time parameters applied:
          - hnsw_ef:      search beam width (higher = better recall, slower)
          - oversampling:  quantization candidate multiplier for rescoring
          - rescore:       rescore candidates with original float32 vectors

        Args:
            query_embedding: Query vector
            top_k: Number of results to return
            filters: Optional filters (e.g., {"doi": "10.1001/..."})
            search_params: Runtime overrides for optimized params (e.g. {"ef_search": 800})

        Returns:
            List of RetrievalResult objects
        """
        client = self._get_client()
        search_start = time.time()

        # Resolve search parameters (Method argument > Instance config > Defaults)
        current_params = search_params or {}
        
        hnsw_ef = current_params.get("ef_search", self._search_hnsw_ef)
        oversampling = current_params.get("oversampling", self._search_oversampling)
        rescore = current_params.get("rescore", self._search_rescore)
        use_quantization = current_params.get("use_quantization", self._use_quantization)

        try:
            # Build filter
            qdrant_filter = None
            if filters:
                conditions = []
                should_conditions = []  # For OR conditions

                for key, value in filters.items():
                    # Special filter: user_id_is_null (for shared_only mode)
                    if key == "user_id_is_null" and value:
                        conditions.append(
                            self._models.IsNullCondition(
                                is_null=self._models.PayloadField(key="user_id")
                            )
                        )
                    # Special filter: user_id_or_null (for "both" mode)
                    elif key == "user_id_or_null":
                        # Match user_id = value OR user_id is NULL
                        should_conditions = [
                            self._models.FieldCondition(
                                key="user_id",
                                match=self._models.MatchValue(value=value)
                            ),
                            self._models.IsNullCondition(
                                is_null=self._models.PayloadField(key="user_id")
                            )
                        ]
                    elif isinstance(value, list):
                        conditions.append(
                            self._models.FieldCondition(
                                key=key,
                                match=self._models.MatchAny(any=value)
                            )
                        )
                    else:
                        conditions.append(
                            self._models.FieldCondition(
                                key=key,
                                match=self._models.MatchValue(value=value)
                            )
                        )
            
            # Construct SearchParams
            search_params_obj = self._models.SearchParams(
                hnsw_ef=hnsw_ef,
                exact=False,  # Always approximate for speed
                quantization=self._models.QuantizationSearchParams(
                    ignore=not use_quantization,
                    rescore=rescore,
                    oversampling=oversampling
                )
            )

            # Log search configuration (debug level to avoid spam)
            logger.debug(
                f"[SEARCH-CONFIG] ef={hnsw_ef}, oversampling={oversampling}, "
                f"rescore={rescore}, quant={use_quantization}"
            )
            
            # Build the final filter
            final_filter = None
            if filters:
                if should_conditions and conditions:
                    # Both must and should conditions
                    final_filter = self._models.Filter(
                        must=conditions,
                        should=should_conditions,
                        min_should=self._models.MinShould(conditions=should_conditions, min_count=1)
                    )
                elif should_conditions:
                    # Only should conditions (OR logic)
                    final_filter = self._models.Filter(should=should_conditions)
                elif conditions:
                    # Only must conditions (AND logic)
                    final_filter = self._models.Filter(must=conditions)

            # Execute search
            # Note: QdrantClient v1.10+ deprecated 'search' in favor of 'query_points'
            response = client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                query_filter=final_filter,
                limit=top_k,
                search_params=search_params_obj,
                with_payload=True,
                with_vectors=False  # We don't need the vector back
            )
            results = response.points



            search_ms = (time.time() - search_start) * 1000
            logger.debug(
                f"[SEARCH] Qdrant returned {len(results)} results in {search_ms:.1f}ms "
                f"(ef={self._search_hnsw_ef}, oversampling={self._search_oversampling}, "
                f"rescore={self._search_rescore}, top_k={top_k})"
            )

            # Convert to RetrievalResult
            retrieval_results = []
            for result in results:
                payload = result.payload

                # Merge enriched fields into metadata
                # Enrichment script adds citation_str, title, authors, year, apa_reference at top level
                enriched_metadata = payload.get("metadata", {}).copy()
                enrichment_fields = [
                    "citation_str", "title", "authors", "year", "venue",
                    "volume", "issue", "first_page", "last_page", "apa_reference"
                ]
                for key in enrichment_fields:
                    if key in payload:
                        enriched_metadata[key] = payload[key]

                chunk = Chunk(
                    chunk_id=result.id,
                    text=payload.get("text", ""),
                    doi=payload.get("doi", ""),
                    section=payload.get("section", ""),
                    chunk_index=payload.get("chunk_index", 0),
                    metadata=enriched_metadata,
                )

                retrieval_results.append(RetrievalResult(
                    chunk=chunk,
                    score=result.score,
                    source="semantic",
                ))

            return retrieval_results

        except Exception as e:
            raise VectorStoreError(
                f"Search failed: {str(e)}",
                {"error": str(e)}
            )
    
    def delete(self, doi: str, user_id: Optional[str] = None) -> None:
        """
        Delete all chunks for a document.

        SECURITY: When user_id is provided, only chunks belonging to that user
        will be deleted. This prevents cross-user data deletion.

        Args:
            doi: DOI of the document to delete
            user_id: User ID for data isolation (required for multi-user mode).
                     If provided, only deletes chunks where user_id matches.
                     If None, deletes all chunks with this DOI (admin/legacy mode).
        """
        client = self._get_client()

        try:
            # Build filter conditions
            filter_conditions = [
                self._models.FieldCondition(
                    key="doi",
                    match=self._models.MatchValue(value=doi)
                )
            ]

            # CRITICAL: Add user_id filter for multi-user isolation
            if user_id:
                filter_conditions.append(
                    self._models.FieldCondition(
                        key="user_id",
                        match=self._models.MatchValue(value=user_id)
                    )
                )
                logger.debug(f"[DELETE] User-isolated delete: doi={doi}, user_id={user_id}")
            else:
                logger.warning(f"[DELETE] No user_id provided - deleting ALL chunks for DOI: {doi}")

            client.delete(
                collection_name=self.collection_name,
                points_selector=self._models.FilterSelector(
                    filter=self._models.Filter(must=filter_conditions)
                )
            )
            logger.info(f"Deleted chunks for DOI: {doi}" + (f" (user_id={user_id})" if user_id else ""))

        except Exception as e:
            raise VectorStoreError(
                f"Delete failed: {str(e)}",
                {"doi": doi, "user_id": user_id, "error": str(e)}
            )
    
    def count(self) -> int:
        """Get total number of chunks."""
        client = self._get_client()
        
        try:
            info = client.get_collection(self.collection_name)
            return info.points_count
        except Exception:
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics including index completeness."""
        client = self._get_client()

        try:
            info = client.get_collection(self.collection_name)
            total   = info.vectors_count or 0
            indexed = info.indexed_vectors_count or 0
            completeness = (indexed / total) if total > 0 else 1.0

            stats = {
                "points_count":          info.points_count,
                "vectors_count":         total,
                "indexed_vectors_count": indexed,
                "index_completeness":    round(completeness, 4),
                "status":                info.status.value,
            }

            # Extract optimizer status
            if hasattr(info, "optimizer_status") and info.optimizer_status:
                opt = info.optimizer_status
                stats["optimizer_status"] = str(
                    getattr(opt, "status", opt)
                )

            return stats
        except Exception as e:
            return {"error": str(e)}

    def check_existing_ids(self, ids: List[str], user_id: Optional[str] = None) -> List[str]:
        """
        Check which IDs already exist in the collection.
        Returns a list of IDs (from the input list) that were found.
        Robustly handles UUID format differences (dashes vs hex).

        SECURITY: When user_id is provided, only returns IDs belonging to that user.
        This prevents information disclosure about other users' documents.

        Args:
            ids: List of chunk IDs to check
            user_id: User ID for data isolation (required for multi-user mode).
                     If provided, only returns IDs where user_id matches.
                     If None, checks globally (admin/legacy mode).

        Returns:
            List of IDs that exist (and belong to user, if user_id specified)
        """
        if not ids:
            return []

        client = self._get_client()
        try:
            # 1. Prepare variations
            # Qdrant might store them as UUID objects (dashed strings).
            # The input might be raw hex.
            # We map "Query ID" -> "Original ID" to return the original format
            query_map = {}
            for original_id in ids:
                query_map[original_id] = original_id  # Map self to self
                try:
                    # If it's a hex string (32 chars), also check the dashed version
                    import uuid
                    if len(original_id) == 32:
                        dashed = str(uuid.UUID(original_id))
                        query_map[dashed] = original_id
                except:
                    pass

            # 2. Query
            unique_query_ids = list(query_map.keys())

            # Batch query if too large
            found_original_ids = set()
            batch_size = 500
            for i in range(0, len(unique_query_ids), batch_size):
                batch = unique_query_ids[i:i + batch_size]
                # Include payload to check user_id if needed
                results = client.retrieve(
                    collection_name=self.collection_name,
                    ids=batch,
                    with_payload=True if user_id else False,
                    with_vectors=False
                )

                # 3. Map back results to input format, with optional user_id filtering
                for record in results:
                    rec_id = str(record.id)
                    if rec_id in query_map:
                        # CRITICAL: Filter by user_id for multi-user isolation
                        if user_id:
                            payload = record.payload or {}
                            record_user_id = payload.get("user_id")
                            # Only include if user_id matches OR record has no user_id (legacy)
                            if record_user_id is not None and record_user_id != user_id:
                                logger.debug(f"[CHECK-IDS] Filtered out {rec_id} - belongs to user {record_user_id}")
                                continue
                        found_original_ids.add(query_map[rec_id])

            if user_id:
                logger.debug(f"[CHECK-IDS] Found {len(found_original_ids)}/{len(ids)} IDs for user_id={user_id}")

            return list(found_original_ids)

        except Exception as e:
            logger.error(f"Failed to check existing IDs: {e}")
            return []


def create_vector_store(
    host: str = "localhost",
    port: int = 6333,
    collection_name: str = "sme_papers",
    embedding_dimension: int = 4096,
    location: Optional[str] = None,
    qdrant_batch_size: int = 100,
    timeout: int = 60,
    optimized_params: Optional[Dict[str, Any]] = None,
) -> QdrantVectorStore:
    """
    Factory function to create an optimized vector store.

    Args:
        optimized_params: Dict from qdrant_optimizer.compute_optimal_params().
                          Controls HNSW config, quantization, and search params.
    """
    return QdrantVectorStore(
        host=host,
        port=port,
        collection_name=collection_name,
        embedding_dimension=embedding_dimension,
        location=location,
        qdrant_batch_size=qdrant_batch_size,
        timeout=timeout,
        optimized_params=optimized_params,
    )
