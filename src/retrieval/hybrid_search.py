"""
SME Research Assistant - Hybrid Search

Combines semantic and BM25 search with reciprocal rank fusion.
"""

import logging
from typing import List, Dict, Any, Optional

from src.core.interfaces import RetrievalResult, Chunk
from src.core.exceptions import RetrievalError
from src.indexing import create_embedder, create_vector_store, create_bm25_index
from src.indexing.qdrant_optimizer import get_optimal_config

logger = logging.getLogger(__name__)


class HybridSearch:
    """
    Hybrid search combining semantic and BM25 retrieval.
    """
    
    def __init__(
        self,
        embedder=None,
        vector_store=None,
        bm25_index=None,
        bm25_weight: float = 0.3,
        semantic_weight: float = 0.7,
        top_k_initial: int = 50
    ):
        """
        Initialize hybrid search.
        
        Args:
            embedder: Embedder instance
            vector_store: Vector store instance
            bm25_index: BM25 index instance
            bm25_weight: Weight for BM25 scores (0-1)
            semantic_weight: Weight for semantic scores (0-1)
            top_k_initial: Initial number of results from each method
        """
        self.embedder = embedder
        self.vector_store = vector_store
        self.bm25_index = bm25_index
        self.bm25_weight = bm25_weight
        self.semantic_weight = semantic_weight
        self.top_k_initial = top_k_initial
    
    def search(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        use_bm25: bool = True,
        use_semantic: bool = True,
        search_params: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None
    ) -> List[RetrievalResult]:
        """
        Perform hybrid search.

        Args:
            query: Search query
            top_k: Number of results to return
            filters: Optional filters for vector search
            use_bm25: Whether to use BM25
            use_semantic: Whether to use semantic search
            search_params: Optional dictionary of search parameters for vector store (e.g. ef_search)
            user_id: Optional user ID for multi-user isolation. If provided, only returns
                     results belonging to this user.

        Returns:
            List of RetrievalResult objects
        """
        if not query or not query.strip():
            return []

        # Multi-user isolation: inject user_id into filters
        if user_id:
            filters = filters.copy() if filters else {}
            filters["user_id"] = user_id
            logger.debug(f"[SEARCH] User isolation active: user_id={user_id}")
        
        results_map: Dict[str, Dict] = {}  # chunk_id -> {chunk, scores}
        
        # Semantic search
        if use_semantic and self.embedder and self.vector_store:
            try:
                query_embedding = self.embedder.embed_query(query)
                # M13 FIX: Use caller's top_k directly (was: max(top_k, self.top_k_initial) which
                # overrode preset-derived values with stale constructor default of 50)
                fetch_k = top_k
                logger.debug(f"Run Semantic Search (fetch_k={fetch_k})...")
                semantic_results = self.vector_store.search(
                    query_embedding,
                    top_k=fetch_k,
                    filters=filters,
                    search_params=search_params
                )
                logger.debug(f"Semantic Search Result Count: {len(semantic_results)}")
                
                # Normalize scores using rank
                for rank, result in enumerate(semantic_results):
                    chunk_id = result.chunk.chunk_id
                    if chunk_id not in results_map:
                        results_map[chunk_id] = {
                            "chunk": result.chunk,
                            "semantic_score": 0,
                            "bm25_score": 0,
                            "semantic_rank": float('inf'),
                            "bm25_rank": float('inf')
                        }
                    results_map[chunk_id]["semantic_score"] = result.score
                    results_map[chunk_id]["semantic_rank"] = rank + 1
                
                # Log details
                if semantic_results:
                    scores = [r.score for r in semantic_results]
                    top_titles = [r.chunk.metadata.get('title', 'Unknown')[:50] for r in semantic_results[:3]]
                    logger.debug(f"  > Semantic Scores: {min(scores):.4f} - {max(scores):.4f}")
                    logger.debug(f"  > Top 3 Semantic: {top_titles}")
                else:
                    logger.warning("  > Semantic Search returned NO results.")
                    
            except Exception as e:
                logger.warning(f"Semantic search failed: {e}")
        
        # BM25 search
        if use_bm25 and self.bm25_index:
            try:
                # M13 FIX: Use caller's top_k directly
                fetch_k = top_k
                logger.debug(f"Run BM25 Search (fetch_k={fetch_k}, user_id={user_id})...")
                bm25_results = self.bm25_index.search(query, top_k=fetch_k, user_id=user_id)
                logger.debug(f"BM25 Search Result Count: {len(bm25_results)}")
                
                for rank, result in enumerate(bm25_results):
                    chunk_id = result.chunk.chunk_id
                    if chunk_id not in results_map:
                        results_map[chunk_id] = {
                            "chunk": result.chunk,
                            "semantic_score": 0,
                            "bm25_score": 0,
                            "semantic_rank": float('inf'),
                            "bm25_rank": float('inf')
                        }
                    results_map[chunk_id]["bm25_score"] = result.score
                    results_map[chunk_id]["bm25_rank"] = rank + 1
                
                # Log details
                if bm25_results:
                    scores = [r.score for r in bm25_results]
                    top_titles = [r.chunk.metadata.get('title', 'Unknown')[:50] for r in bm25_results[:3]]
                    logger.debug(f"  > BM25 Scores: {min(scores):.4f} - {max(scores):.4f}")
                    logger.debug(f"  > Top 3 BM25: {top_titles}")
                else:
                    logger.warning("  > BM25 Search returned NO results.")
                    
            except Exception as e:
                logger.warning(f"BM25 search failed: {e}")
        
        if not results_map:
            return []
        
        # Combine scores using Reciprocal Rank Fusion
        # RRF: Reciprocal Rank Fusion (using centralized constant)
        from src.config.thresholds import RRF_K
        k = RRF_K
        
        combined_results = []  # Initialize results list
        
        for chunk_id, data in results_map.items():
            # RRF score
            rrf_semantic = 1.0 / (k + data["semantic_rank"]) if data["semantic_rank"] < float('inf') else 0
            rrf_bm25 = 1.0 / (k + data["bm25_rank"]) if data["bm25_rank"] < float('inf') else 0
            
            combined_score = (
                self.semantic_weight * rrf_semantic +
                self.bm25_weight * rrf_bm25
            )
            
            combined_results.append(RetrievalResult(
                chunk=data["chunk"],
                score=combined_score,
                source="hybrid",
                metadata={
                    "semantic_score": data["semantic_score"],
                    "bm25_score": data["bm25_score"],
                    "semantic_rank": data["semantic_rank"],
                    "bm25_rank": data["bm25_rank"]
                }
            ))
        
        # Sort by combined score
        combined_results.sort(key=lambda x: x.score, reverse=True)
        
        # Log Intersection and Final Top 5
        intersect_count = sum(1 for d in results_map.values() if d["semantic_rank"] != float('inf') and d["bm25_rank"] != float('inf'))
        logger.info(f"Search Intersection: {intersect_count} documents found by BOTH methods.")
        
        top_final = combined_results[:5]
        logger.info(f"Final Hybrid Top 5:")
        for i, r in enumerate(top_final):
            title = r.chunk.metadata.get('title', 'Unknown')[:60]
            logger.info(f"  {i+1}. [{r.score:.4f}] {title}")
            
        return combined_results[:top_k]


def create_hybrid_search(
    config: Dict[str, Any] = None
) -> HybridSearch:
    """Factory function to create hybrid search with config."""
    config = config or {}
    
    embedder_config = config.get("embedding", {})
    vector_config = config.get("vector_store", {})
    bm25_config = config.get("bm25", {})
    retrieval_config = config.get("retrieval", {})
    
    # Get hardware-optimized parameters
    # If provided in config (from run_startup_optimization), use them.
    # Otherwise, fallback to default estimation (which assumes 100k vectors).
    optimized_params = config.get("optimized_params")
    if not optimized_params:
        logger.warning("[HYBRID-INIT] No optimized params provided in config. Using defaults (100k vectors).")
        optimized_params = get_optimal_config()
    
    logger.info(f"[HYBRID-INIT] ✅ Configuration Loaded: Using optimized Qdrant parameters (Tier={optimized_params.get('tier', 'Unknown')})\n"
                f"              -> Params injected into Vector Store initialization.")

    vector_store = create_vector_store(
        host=vector_config.get("host", "localhost"),
        port=vector_config.get("port", 6333),
        collection_name=vector_config.get("collection_name", "sme_papers"),
        embedding_dimension=embedder_config.get("dimension", 4096),
        timeout=vector_config.get("timeout", 10),
        optimized_params=optimized_params
    )

    return HybridSearch(
        embedder=create_embedder(
            model_name=embedder_config.get("model_name", "Qwen/Qwen3-Embedding-8B"),
            device=embedder_config.get("device", "cuda"),
            batch_size=embedder_config.get("batch_size", 32),
            quantization=embedder_config.get("quantization", "4bit"),
            remote_url=embedder_config.get("remote_url")
        ),
        vector_store=vector_store,
        bm25_index=create_bm25_index(
            index_path=bm25_config.get("index_path", "data/bm25_index.pkl"),
            remove_stopwords=bm25_config.get("remove_stopwords", True),
            tokenizer_type=bm25_config.get("tokenizer", "word"),
            vector_store=vector_store,
            use_tantivy=True
        ),
        bm25_weight=retrieval_config.get("bm25_weight", 0.3),
        semantic_weight=retrieval_config.get("semantic_weight", 0.7),
        top_k_initial=retrieval_config.get("top_k_initial", 50)
    )
