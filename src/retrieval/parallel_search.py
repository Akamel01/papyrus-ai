"""
Parallel Search Executor for Sequential RAG.

Executes multiple follow-up searches concurrently for faster processing.

.. deprecated:: 1.0
    This module is DEPRECATED and NOT USED in the codebase.
    It lacks user_id filtering required for multi-user data isolation.
    Do NOT use this module - use src/retrieval/sequential/search.py instead,
    which properly propagates user_id for data isolation.

    If you need parallel search functionality, it must be implemented with
    user_id support. See SECURITY.md for multi-user isolation requirements.

SECURITY WARNING:
    This module does NOT support user_id filtering. Using it would allow
    cross-user data access, which is a critical security vulnerability.
"""
import warnings

warnings.warn(
    "parallel_search.py is deprecated and lacks user_id isolation. "
    "Use src/retrieval/sequential/search.py instead.",
    DeprecationWarning,
    stacklevel=2
)

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Result from a single search."""
    query: str
    context: str
    results: List
    apa_refs: List[str]
    doi_map: Dict[str, int]
    success: bool
    error: Optional[str] = None


class ParallelSearchExecutor:
    """
    Execute multiple searches in parallel using ThreadPoolExecutor.
    """
    
    def __init__(self, pipeline: dict, max_workers: int = 3, timeout: int = 90):
        """
        Initialize parallel search executor.
        
        Args:
            pipeline: RAG pipeline components
            max_workers: Max concurrent searches
            timeout: Timeout in seconds for all searches
        """
        self.pipeline = pipeline
        self.max_workers = max_workers
        self.timeout = timeout
    
    def search_parallel(
        self,
        queries: List[str],
        preset: dict,
        paper_range: Tuple[int, int]
    ) -> List[SearchResult]:
        """
        Execute multiple searches in parallel.
        
        Args:
            queries: List of search queries
            preset: Depth preset hyperparameters
            paper_range: (min_papers, max_papers)
            
        Returns:
            List of SearchResult objects
        """
        if not queries:
            return []
        
        # Single query - no parallelism needed
        if len(queries) == 1:
            result = self._do_single_search(queries[0], preset, paper_range)
            return [result]
        
        results = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all searches
            future_to_query = {
                executor.submit(self._do_single_search, q, preset, paper_range): q
                for q in queries
            }
            
            # Collect results as they complete
            try:
                for future in as_completed(future_to_query, timeout=self.timeout):
                    query = future_to_query[future]
                    try:
                        result = future.result()
                        results.append(result)
                        logger.info(f"Parallel search completed: {query[:50]}...")
                    except Exception as e:
                        logger.error(f"Search failed for '{query[:50]}...': {e}")
                        results.append(SearchResult(
                            query=query,
                            context="",
                            results=[],
                            apa_refs=[],
                            doi_map={},
                            success=False,
                            error=str(e)
                        ))
            except TimeoutError:
                logger.warning(f"Parallel search timed out after {self.timeout}s")
        
        return results
    
    def _do_single_search(
        self,
        query: str,
        preset: dict,
        paper_range: Tuple[int, int]
    ) -> SearchResult:
        """Execute a single search."""
        try:
            hybrid_search = self.pipeline["hybrid_search"]
            reranker = self.pipeline["reranker"]
            context_builder = self.pipeline["context_builder"]
            
            min_papers, max_papers = paper_range
            
            # Search with expanded limits
            initial_k = max(preset["top_k_initial"], max_papers * 3)
            results = hybrid_search.search(query, top_k=initial_k)
            
            # Rerank
            rerank_k = max(preset["top_k_rerank"], max_papers * 2)
            reranked = reranker.rerank(query, results, top_k=rerank_k)
            
            # Build context
            context, used_results, apa_refs, doi_map = context_builder.build_context(
                reranked,
                max_per_doi=preset.get("max_per_doi", 2),
                min_unique_papers=min_papers,
                max_unique_papers=max_papers
            )
            
            return SearchResult(
                query=query,
                context=context,
                results=used_results,
                apa_refs=apa_refs,
                doi_map=doi_map,
                success=True
            )
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return SearchResult(
                query=query,
                context="",
                results=[],
                apa_refs=[],
                doi_map={},
                success=False,
                error=str(e)
            )
    
    def merge_results(self, search_results: List[SearchResult]) -> Tuple[str, List, List[str], Dict[str, int]]:
        """
        Merge multiple search results into unified context.
        
        Returns:
            Tuple of (merged_context, all_results, all_refs, merged_doi_map)
        """
        contexts = []
        all_results = []
        all_refs = []
        merged_doi_map = {}
        current_num = 0
        
        for sr in search_results:
            if not sr.success:
                continue
            
            # Add context
            contexts.append(f"--- Search: {sr.query[:50]}... ---\n{sr.context}")
            
            # Add results (avoiding duplicates by DOI)
            for r in sr.results:
                doi = r.chunk.doi if hasattr(r, 'chunk') else None
                if doi and doi not in merged_doi_map:
                    current_num += 1
                    merged_doi_map[doi] = current_num
                    all_results.append(r)
            
            # Add unique refs
            for ref in sr.apa_refs:
                if ref not in all_refs:
                    all_refs.append(ref)
        
        merged_context = "\n\n".join(contexts)
        return merged_context, all_results, all_refs, merged_doi_map


def create_parallel_executor(pipeline: dict, max_workers: int = 3) -> ParallelSearchExecutor:
    """Factory function to create parallel executor."""
    return ParallelSearchExecutor(pipeline, max_workers=max_workers)
