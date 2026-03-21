"""
RAG Pipeline Wrappers.

Adapts existing backend components to the API expected by main.py.
"""

from typing import List, Dict, Tuple, Any, Optional
from src.retrieval.hybrid_search import HybridSearch
from src.retrieval.sequential_rag import SequentialRAG
from src.core.interfaces import RetrievalResult

class RetrieverWrapper:
    """Wraps HybridSearch to expose a simple .retrieve interface."""

    def __init__(self, hybrid_search: HybridSearch):
        self.hybrid_search = hybrid_search

    def retrieve(self, query: str, top_k: int, user_id: Optional[str] = None) -> List[RetrievalResult]:
        """Retrieve relevant documents.

        Args:
            query: Search query
            top_k: Number of results
            user_id: Optional user ID for multi-user isolation
        """
        # Use existing search method with user_id for multi-user filtering
        return self.hybrid_search.search(query, top_k=top_k, user_id=user_id)


class RAGWrapper:
    """Wraps generation logic to expose .generate and .generate_sequential interfaces."""
    
    def __init__(self, pipeline: dict, sequential_rag: SequentialRAG = None):
        self.pipeline = pipeline
        self.sequential_rag = sequential_rag or SequentialRAG(pipeline)
        
    def generate(self, query: str, depth: str, model: str, paper_range: Tuple[int, int],
                 citation_density: str, auto_citation_density: bool,
                 user_id: Optional[str] = None,
                 **kwargs):
        """Standard generation method (Non-sequential).

        Args:
            user_id: Optional user ID for multi-user isolation
        """
        # Import local process_query from main (circular import avoidance or duplicate logic)
        # Ideally, main.py's process_query should be moved here or imported.
        # But for now, we can implement the logic here using pipeline components.
        
        # We need to replicate process_query logic OR call it if it's available.
        # Since main.py already has key logic, we should probably refactor functionality OUT of main.py
        # But to be safe and quick, let's import the functionality from a new module if possible
        # OR just implement a lightweight version calling the components.
        
        # Actually, main.py calls `process_query` for standard RAG if sequential is disabled logic is slightly mixed.
        # But calling code for standard RAG in main.py Step 22 is:
        # process_func = pipeline["rag"].generate_sequential if cfg["enable_sequential"] else pipeline["rag"].generate
        
        # So we need to implement `generate` here.
        
        # We have the retrieved context passed in? 
        # Wait, the calling code for standard RAG in Step 22:
        # 1. Calls retrieve() -> results
        # 2. Calls process_func(query, retrieved_context=results, ...)
        
        # So we need to take `retrieved_context` as arg.
        retrieved_context = kwargs.get("retrieved_context", [])
        
        # Logic for Standard RAG generation
        # 1. Rerank
        reranker = self.pipeline["reranker"]
        # Convert RetrievalResult list to format expected by reranker if needed? 
        # Reranker expects list of RetrievalResult.
        
        # Get depth presets for top_k_rerank
        from src.config.depth_presets import get_depth_preset
        preset = get_depth_preset(depth)
        
        reranked = reranker.rerank(query, retrieved_context, top_k=preset["top_k_rerank"])
        
        # 2. Build Context
        context_builder = self.pipeline["context_builder"]
        # Resolve paper targets
        min_papers = preset["min_unique_papers"]
        max_papers = preset["min_unique_papers"] * 2
        
        context_text, used_results, apa_refs, doi_map = context_builder.build_context(
            reranked,
            max_per_doi=preset["max_per_doi"],
            min_unique_papers=min_papers,
            max_unique_papers=max_papers
        )
        
        # 3. Generate
        prompt_builder = self.pipeline["prompt_builder"]
        # Basic context prompt
        # We'll need conversation history
        conv_hist = kwargs.get("conversation_history", [])
        
        base_prompt = prompt_builder.build_rag_prompt(
            query=query,
            context=context_text,
            conversation_history=conv_hist
        )
        
        # Add citation instructions
        try:
            from src.utils.citation_density import get_citation_instructions
            citation_instr = get_citation_instructions(
                query=query,
                depth=depth,
                density_level=citation_density or "Medium",
                auto_decide=auto_citation_density
            )
            prompt = base_prompt + citation_instr
        except Exception:
            prompt = base_prompt
            
        llm = self.pipeline["llm"]
        response = llm.generate(
            prompt=prompt,
            system_prompt=prompt_builder.system_prompt,
            temperature=preset["temperature"],
            max_tokens=preset["max_tokens"],
            model=model
        )
        
        # 4. Validate
        try:
            from src.generation import validate_response, get_compliance_badge
            validation = validate_response(response, num_sources=len(used_results))
            compliance_badge = get_compliance_badge(validation.compliance_score)
            
            # P9 FIX / STANDARD RAG: Extract confirmed citations and append ## References natively
            # Match DOIs backwards from ValidationResult.cited_sources [1...N]
            cited_dois = set()
            for source_idx in validation.cited_sources:
                # Find the doi that matches this index in doi_map
                for doi, idx in doi_map.items():
                    if idx == source_idx:
                        cited_dois.add(doi)
                        break
            
            # Use the deterministic Split-by-DOI logic identical to Section Mode
            from src.utils.reference_splitter import split_references_by_doi, format_split_references
            
            cited_refs, uncited_refs = split_references_by_doi(apa_refs, cited_dois)
            formatted_refs = format_split_references(cited_refs, uncited_refs)
            
            # Append cleanly to the response string exactly like SequentialRAG
            response += f"\n\n---\n\n## References\n\n{formatted_refs}"
            
        except Exception as e:
            compliance_badge = "⚪ N/A"
            # Fallback (won't crash the pipeline, references will just be handled by UI)
            pass
            
        # 5. Determine Confidence (using centralized thresholds)
        from src.config.thresholds import get_confidence_level
        unique_count = len(doi_map)
        confidence = get_confidence_level(unique_count)
            
        # 6. Format Sources
        sources_list = []
        for r in used_results:
            doi = r.chunk.doi
            paper_num = doi_map.get(doi, 0)
            sources_list.append({
                "paper_num": paper_num,
                "citation": r.chunk.metadata.get("citation_str", f"[{doi}]"),
                "apa_reference": r.chunk.metadata.get("apa_reference", ""),
                "title": r.chunk.metadata.get("title", ""),
                "doi": doi,
                "score": r.score,
                "preview": r.chunk.text[:300] + "..."
            })
            
        # Helper to match signature expected by main.py
        # unpack: response, sources, confidence, apa_references, compliance_badge, doi_to_number, reflection_log_data
        
        reflection_log_data = [] # None for standard
        
        return response, sources_list, confidence, apa_refs, compliance_badge, doi_map, reflection_log_data


    def generate_sequential(self, query: str, user_id: Optional[str] = None, **kwargs):
        """Sequential generation method.

        NOTE: SequentialRAG performs its own multi-round search internally,
        so we do NOT accept/use retrieved_context here.

        Args:
            user_id: Optional user ID for multi-user isolation
        """
        # kwargs needed: depth, model, paper_range, conversation_history, citation_density, auto_citation_density, status_callback

        # Pop retrieved_context if passed (for backwards compatibility) but don't use it
        kwargs.pop("retrieved_context", None)

        response, sources, confidence, apa_refs, compliance_badge, doi_map = self.sequential_rag.process_with_reflection(
            query=query,
            depth=kwargs["depth"],
            model=kwargs["model"],
            paper_range=kwargs["paper_range"],
            conversation_history=kwargs.get("conversation_history"),
            citation_density=kwargs.get("citation_density"),
            auto_citation_density=kwargs.get("auto_citation_density", True),
            status_callback=kwargs.get("status_callback"),
            user_id=user_id
        )

        return response, sources, confidence, apa_refs, compliance_badge, doi_map, self.sequential_rag.reflection_log

