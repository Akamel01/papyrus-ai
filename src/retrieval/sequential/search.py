"""
Search Mixin for Sequential RAG.

Search and retrieval operations:
- Multi-round search with query expansion
- HyDE search integration
- Reactive audit step
- Source extraction
"""

import re
import logging
from typing import List, Dict, Tuple, Optional, Any

from src.utils.monitoring import StepTracker
from src.utils.diagnostics import DiagnosticGate # Diagnostic System

logger = logging.getLogger(__name__)


class SearchMixin:
    """
    Mixin providing search and retrieval capabilities.
    
    Requires:
        - self.pipeline with "hybrid_search", "reranker", "context_builder", "llm" keys
    """
    
    def _do_search(
        self,
        query: str,
        preset: dict,
        model: str,
        paper_range: Tuple[int, int],
        depth: str = "Medium",
        inject_results: List = None,
        context_builder: Optional[Any] = None,
        max_per_doi: Optional[int] = None,
        search_params: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,  # Multi-user isolation
        knowledge_source: str = "both"  # "shared_only", "user_only", or "both"
    ) -> Tuple[str, List, List[str], Dict[str, int]]:
        """
        Perform a single search round with query expansion.
        
        Args:
            query: Search query
            preset: Depth preset configuration
            model: LLM model to use
            paper_range: (min_papers, max_papers) tuple
            depth: Research depth level
            inject_results: Optional list of results to inject (e.g. from Phase 1) to be reranked
            search_params: Runtime search parameters (e.g., {"ef_search": 800})
            
        Returns:
            Tuple of (context, results, apa_refs, doi_map)
        """
        hybrid_search = self.pipeline["hybrid_search"]
        reranker = self.pipeline["reranker"]
        # Use provided builder or fallback to pipeline default
        context_builder = context_builder if context_builder else self.pipeline["context_builder"]
        
        # FIX (H1): Use preset values directly (per query/sub-query, not combined)
        min_papers, max_papers = paper_range
        initial_k = preset["top_k_initial"]
        rerank_k = preset["top_k_rerank"]
        
        logger.info(f"Search Strategy (Depth={depth}): Target Papers {paper_range} -> Fetching {initial_k} candidates/query, Reranking Top {rerank_k}.")
        
        # Step 1: Query Expansion
        use_query_expansion = preset.get("use_query_expansion", True)
        min_sub, max_sub = preset.get("sub_query_limit", (1, 2))
        sub_queries = [query]
        
        if use_query_expansion:
            try:
                from src.retrieval import create_query_expander
                expander = create_query_expander(llm_client=self.pipeline.get("llm"))
                
                with StepTracker("Query Expansion"):
                    logger.info(f"Depth '{depth}': Enforcing strict sub-query usage: {min_sub}-{max_sub}")
                    
                    sub_queries = [] # Initialize for safety
                    with DiagnosticGate(
                        "Query Expansion", 
                        severity="warning", 
                        context={"query": query}, 
                        suppress=True
                    ) as gate:
                        try:
                            # Pass strict limits to expander
                            sub_queries = expander.decompose_query(
                                query, 
                                model=model, 
                                min_queries=min_sub, 
                                max_queries=max_sub
                            )
                            
                            # Enforce Limits (Truncation)
                            if len(sub_queries) > max_sub:
                                logger.warning(f"Constraint Violation: Generated {len(sub_queries)} queries (Max {max_sub}). Truncating.")
                                sub_queries = sub_queries[:max_sub]
                            
                            # Enforce Limits (Padding/Fallback handled in expander ideally, but check here)
                            if len(sub_queries) < min_sub:
                                logger.warning(f"Constraint Warning: Generated {len(sub_queries)} queries (Min {min_sub}).")
                                # If empty, ensure meaningful default
                                if not sub_queries:
                                    sub_queries = [query]
                                    
                            gate.set_success_message(f"Expanded into {len(sub_queries)} sub-queries")
                            logger.info(f"Final Plan: {len(sub_queries)} sub-queries")
                            gate.context["sub_queries"] = sub_queries
                        except Exception as e:
                             logger.warning(f"Query expansion failed: {e}")
                             raise e
            except Exception as e:
                logger.warning(f"Query Expander setup failed: {e}")
                
        # Gate for expansion wrapping if not internal
        if use_query_expansion and not sub_queries:
             pass # Logic handled above or in expander
        
        # Step 1.5: HyDE Search (Hypothetical Document Embeddings)
        use_hyde = preset.get("use_hyde", True)
        all_results = []
        
        if use_hyde:
            try:
                from src.retrieval import create_hyde_retriever
                hyde = create_hyde_retriever(
                    llm_client=self.pipeline["llm"],
                    embedder=hybrid_search.embedder,
                    vector_store=hybrid_search.vector_store,
                    top_k=initial_k
                )
            except Exception as e:
                logger.warning(f"HyDE setup failed: {e}")

            if 'hyde' in locals():
                hyde_results = [] # Initialize for safety
                with DiagnosticGate(
                    "HyDE Generation",
                    severity="warning",
                    context={"query": query},
                    suppress=True
                ) as gate:
                    try:
                        hyde_results = hyde.search(query, use_hyde=True, model=model, search_params=search_params, user_id=user_id)
                        all_results.extend(hyde_results)
                        logger.info(f"Sequential RAG: HyDE added {len(hyde_results)} results")
                        gate.context["result_count"] = len(hyde_results)
                        gate.set_success_message(f"Generated {len(hyde_results)} hypothetical passages")
                    except Exception as e:
                        raise e # Report and suppress handled by gate config if needed, default raises
        
        # 2. Hybrid Search
        with StepTracker("Phase 1 Search") as tracker:
            tracker.log_input("query", query)
            tracker.log_metadata("paper_range", paper_range)
            
            # Step 2a: Search for main query
            # CRITICAL: Enabled suppression to prevent search subsystem failure from crashing app
            with DiagnosticGate(
                "Primary Hybrid Search", 
                severity="critical", 
                context={"query": query}, 
                suppress=True
            ) as gate:
                # FIX (C3): Use extend() to preserve HyDE results already in all_results
                primary_results = self.pipeline["hybrid_search"].search(
                    query=query,
                    top_k=preset["top_k_initial"],
                    use_bm25=preset.get("use_bm25", True),
                    use_semantic=preset.get("use_semantic", True),
                    search_params=search_params,
                    user_id=user_id,  # Multi-user isolation
                    knowledge_source=knowledge_source  # Knowledge source filter
                )
                all_results.extend(primary_results)
                gate.context["hits"] = len(primary_results)
                unique_docs = len({r.chunk.doi for r in all_results}) if all_results else 0
                gate.set_success_message(f"Search candidates found: {unique_docs} papers ({len(all_results)} chunks)")
            
            # Fallback if primary search encountered critical error
            if 'all_results' not in locals():
                logger.error("Primary search failed (suppressed). Proceeding with empty results.")
                all_results = []
            
            # Step 2b: Search for sub-queries (if any)
            sub_query_count = 0
            for sub_q in sub_queries:
                if sub_q != query:
                    # FIX (H1): Each sub-query gets full top_k_initial (per-query, not divided)
                    sub_results = self.pipeline["hybrid_search"].search(
                        sub_q, top_k=preset["top_k_initial"], search_params=search_params, user_id=user_id
                    )
                    all_results.extend(sub_results)
                    sub_query_count += 1
            
            # M14 FIX: Single consolidated summary instead of 9 per-call info logs
            if sub_query_count > 0:
                unique_sub_papers = len({r.chunk.doi for r in all_results}) if all_results else 0
                logger.info(f"Hybrid Search Summary: {sub_query_count + 1} searches (1 primary + {sub_query_count} sub-queries) → "
                           f"{len(all_results)} raw chunks from ~{unique_sub_papers} papers")
            
            # Step 2c: Inject external results (e.g. from Phase 1)
            if inject_results:
                logger.info(f"Injecting {len(inject_results)} existing results into search pool")
                tracker.log_metadata("injected_results", len(inject_results))
                all_results.extend(inject_results)

            tracker.log_output("raw_hits", len(all_results))
            
            # Deduplicate results by chunk_id
            seen_ids = set()
            deduped_results = []
            for r in all_results:
                if r.chunk.chunk_id not in seen_ids:
                    seen_ids.add(r.chunk.chunk_id)
                    deduped_results.append(r)
            all_results = deduped_results
            
        # --- REACTIVE AUDIT STEP ---
        should_audit = (depth in ["Medium", "High"]) and all_results
        
        if should_audit:
            decision, details = self._audit_search_results(query, all_results[:10], model)
            
            if decision == "MISSING":
                # Sanitize for Windows console
                safe_details = details.encode('ascii', 'replace').decode('ascii')
                logger.info(f"Audit: MISSING aspect '{safe_details}'. Augmenting search.")
                with StepTracker(f"Reactive Search: {details}"):
                    missing_results = hybrid_search.search(details, top_k=initial_k, search_params=search_params, user_id=user_id)
                    all_results.extend(missing_results)
                    
            elif decision == "RESTRUCTURE":
                logger.info("Audit: RESTRUCTURE required. Converting to atomic sub-queries.")
                with StepTracker("Reactive Restructure"):
                    if 'expander' not in locals():
                        from src.retrieval import create_query_expander
                        expander = create_query_expander(llm_client=self.pipeline.get("llm"))
                    atomic_queries = expander.decompose_query(query, model=model)
                    
                    if set(atomic_queries) != {query}:
                        all_results = []
                        for aq in atomic_queries:
                            sub_results = hybrid_search.search(aq, top_k=initial_k, search_params=search_params, user_id=user_id)
                            all_results.extend(sub_results)
            else:
                logger.info("Audit: SUFFICIENT Coverage.")

        # Deduplicate again after reactive searches
        seen_ids = set()
        final_search_pool = []
        for r in all_results:
            if r.chunk.chunk_id not in seen_ids:
                seen_ids.add(r.chunk.chunk_id)
                final_search_pool.append(r)

        logger.info(f"Total Unique Candidates for Reranking: {len(final_search_pool)}")

        # 3. Reranking
        with StepTracker("Reranking") as rerank_tracker:
            reranked_results = self.pipeline["reranker"].rerank(
                query=query,
                results=final_search_pool,
                top_k=rerank_k
            )
            rerank_tracker.log_output("reranked_count", len(reranked_results))
            logger.info(f"Reranking Complete. Shortlisted top {len(reranked_results)} chunks.")
            
            if reranked_results:
                best_score = reranked_results[0].score
                worst_score = reranked_results[-1].score
                logger.info(f"Reranking Quality: Best Score = {best_score:.4f}, Cutoff Score = {worst_score:.4f}")
        
        # Build context with paper range
        actual_max_per_doi = max_per_doi if max_per_doi is not None else preset.get("max_per_doi", 3)
        
        context, used_results, apa_refs, doi_map = context_builder.build_context(
            reranked_results,
            max_per_doi=actual_max_per_doi,
            min_unique_papers=min_papers,
            max_unique_papers=max_papers
        )
        
        # H9 FIX: Return reranked_results so downstream (landscape, injection) get full set
        return context, used_results, apa_refs, doi_map, reranked_results

    def _audit_search_results(
        self,
        query: str,
        results: List[Dict],
        model: str
    ) -> Tuple[str, Optional[str]]:
        """
        Audit the initial search results for coverage.
        
        Returns:
            Tuple: (Decision [SUFFICIENT|MISSING|RESTRUCTURE], Details [query/concepts])
        """
        if not results:
            return "RESTRUCTURE", None
            
        llm = self.pipeline["llm"]
        
        # Prepare abbreviated results for audit
        audit_view = ""
        for i, r in enumerate(results[:10]):
            title = r.chunk.metadata.get('title', 'Unknown')
            snippet = r.chunk.text[:100]
            audit_view += f"{i+1}. {title} - {snippet}...\n"
            
        prompt = f"""Review these search results for the user's query.
        
QUERY: "{query}"

RESULTS (Top 10):
{audit_view}

TASK: Does this result set cover ALL distinct aspects of the query?
1. Identify Key Information Needs (KINs) from the query.
2. Check if the snippets likely cover these needs.

DECISION RULES:
- If ALL KINs are covered -> Return "SUFFICIENT"
- If a specific topic is COMPLETELY ABSENT -> Return "MISSING: [search term]"
- If results are largely irrelevant or query is too complex -> Return "RESTRUCTURE"

RESPONSE FORMAT:
One line only:
DECISION: [SUFFICIENT | MISSING: <term> | RESTRUCTURE]"""

        try:
            response = llm.generate(
                prompt=prompt,
                system_prompt="Be concise. Do not explain obvious definitions.",
                temperature=0.1,
                max_tokens=4000,  # H2: was 1000 (4×)
                model=model
            )
            
            response = response.strip()
            
            if "RESTRUCTURE" in response:
                return "RESTRUCTURE", None
            elif "MISSING:" in response:
                term = response.split("MISSING:", 1)[1].strip()
                return "MISSING", term
            else:
                return "SUFFICIENT", None
                
        except Exception as e:
            logger.warning(f"Audit failed: {e}")
            return "SUFFICIENT", None
            
    # Wrapped inside _audit_search_results call logic in main flow
    def _auditor_wrapper(self, *args, **kwargs):
        with DiagnosticGate("Search Audit", severity="warning") as gate:
            return self._audit_search_results(*args, **kwargs)

    def _generate_follow_up_queries(
        self,
        original_query: str,
        model: str,
        initial_results: list = None
    ) -> List[str]:
        """Generate specific follow-up sub-queries using LLM.
        
        H4 FIX: When initial_results are provided, generates hierarchical
        micro-level queries that drill into specific subtopics discovered
        in Round 1, rather than generic broadening queries.
        """
        llm = self.pipeline["llm"]
        
        # Build context from initial results if available
        results_context = ""
        if initial_results:
            topics_seen = set()
            for r in initial_results[:30]:  # Sample top 30 results
                title = r.chunk.metadata.get("title", "")
                if title:
                    topics_seen.add(title[:80])
            results_context = (
                f"\n\nPAPERS ALREADY FOUND ({len(initial_results)} results, showing sample titles):\n"
                + "\n".join(f"- {t}" for t in list(topics_seen)[:15])
                + "\n\nGenerate queries that DRILL DEEPER into specific subtopics, "
                "methodological gaps, or unexplored angles NOT already covered above."
            )
        
        prompt = f"""You are a research search query generator performing HIERARCHICAL follow-up.

The user asked: "{original_query}"
{results_context}

Generate 2-3 SPECIFIC follow-up search queries that would find:
1. Different methodological approaches NOT yet covered (e.g., "empirical before-after studies", "meta-analysis")
2. Quantitative data/statistics on specific subtopics (e.g., "crash modification factors", "percentage reduction")
3. Contrasting perspectives, minority viewpoints, or edge cases

RULES:
- Each query should be 5-15 words, focused on a SPECIFIC subtopic
- Use technical terminology from the domain
- Do NOT repeat the original query or topics already well-covered
- Target GAPS in the current evidence base

Return ONLY the queries, one per line, no numbering or explanations."""
        
        try:
            response = llm.generate(
                prompt=prompt,
                system_prompt="You are a search query generator for hierarchical academic research. Return only search queries.",
                temperature=0.4,
                max_tokens=600,  # H2: was 150 (4x)
                model=model
            )
            queries = [q.strip() for q in response.strip().split("\n") if q.strip() and len(q.strip()) > 5]
            logger.info(f"Generated hierarchical follow-up queries: {queries[:3]}")
            return queries[:3]
        except Exception as e:
            logger.warning(f"Follow-up query generation failed: {e}")
            return [f"additional evidence for {original_query[:50]}"]

    def _extract_sources(
        self,
        results: List,
        doi_map: Dict[str, int]
    ) -> List[Dict]:
        """Extract source information from results."""
        sources = []
        seen_dois = set()
        
        for r in results:
            doi = r.chunk.doi
            if doi in seen_dois:
                continue
            seen_dois.add(doi)
            
            paper_num = doi_map.get(doi, 0)
            
            # Build citation string from metadata
            authors = r.chunk.metadata.get("authors", "Unknown")
            year = r.chunk.metadata.get("publication_year", "N/A")
            citation_str = f"{authors} ({year})"
            
            sources.append({
                "paper_num": paper_num,
                "citation": citation_str,
                "title": r.chunk.metadata.get("title", "Untitled"),
                "authors": authors,
                "year": year,
                "doi": doi,
                "preview": r.chunk.text[:300] + "...",
                "score": getattr(r, 'score', 0.0),
                "apa_reference": r.chunk.metadata.get("apa_reference", "")
            })
        
        return sources
