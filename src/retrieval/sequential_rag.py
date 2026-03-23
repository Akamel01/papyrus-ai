"""
Sequential Thinking RAG.

Multi-round RAG where LLM can request additional searches based on initial findings.
Supports section-by-section generation with streaming for improved citation density.

This is the main orchestrator class. Method implementations are in:
- src/retrieval/sequential/search.py (SearchMixin)
- src/retrieval/sequential/reflection.py (ReflectionMixin)
- src/retrieval/sequential/planning.py (PlanningMixin)
- src/retrieval/sequential/generation.py (GenerationMixin)
- src/retrieval/sequential/proofreading.py (ProofreadingMixin)
"""

import logging
from typing import List, Dict, Tuple, Generator
from src.utils.monitoring import StepTracker, start_run, end_run
from src.utils.diagnostics import DiagnosticGate # Diagnostic System
from src.utils.reference_splitter import split_references, format_split_references, split_references_by_doi
from src.utils.adaptive_tokens import AdaptiveTokenManager
from src.retrieval.context_builder import ContextBuilder

# Import from modular structure
from src.retrieval.sequential import (
    SearchRound,
    SectionResult,
    GenerationProgress,
    is_final_section,
    FINAL_SECTION_PATTERNS,
    SearchMixin,
    ReflectionMixin,
    PlanningMixin,
    GenerationMixin,
    ProofreadingMixin,
)
from src.academic_v2.engine import AcademicEngine

logger = logging.getLogger(__name__)


class SequentialRAG(
    SearchMixin,
    ReflectionMixin,
    PlanningMixin,
    GenerationMixin,
    ProofreadingMixin
):
    """
    Sequential RAG with LLM reflection.
    
    The LLM analyzes initial results and can request additional searches
    for more specific information before generating the final response.
    
    This class inherits from mixins that provide:
    - SearchMixin: _do_search, _audit_search_results, _generate_follow_up_queries, _extract_sources
    - ReflectionMixin: _ask_for_more_info, get_search_summary, get_reflection_log
    - PlanningMixin: _determine_section_count, _generate_topic_landscape, _orchestrate_sections, etc.
    - GenerationMixin: _generate_section, _generate_final_section, _aggregate_references, etc.
    - ProofreadingMixin: _multipass_proofread, _proofread_pass1, _proofread_pass2, _proofread_pass3a, etc.
    """

    def __init__(
        self,
        pipeline: dict,
        max_rounds: int = 2,
        enable_reflection: bool = True
    ):
        """
        Initialize Sequential RAG.
        
        Args:
            pipeline: RAG pipeline components
            max_rounds: Maximum search rounds (including initial)
            enable_reflection: Whether to ask LLM if more info needed
        """
        self.pipeline = pipeline
        self.max_rounds = max_rounds
        self.enable_reflection = enable_reflection
        self.search_history: List[SearchRound] = []
        self.reflection_log: List[Dict] = []  # Stores reflection decisions for UI visibility
        self._last_result = None  # Stores final result from process_with_sections generator
        
        # Initialize Academic Engine V2
        self.academic_engine = AcademicEngine(self.pipeline["llm"])
    
    def process_with_reflection(
        self,
        query: str,
        depth: str,
        model: str,
        paper_range: Tuple[int, int],
        conversation_history: List[Dict] = None,
        citation_density: str = None,
        auto_citation_density: bool = True,
        status_callback: callable = None,  # New callback for live UI updates
        user_id: str = None,  # Multi-user isolation
        knowledge_source: str = "both",  # "shared_only", "user_only", or "both"
        quick_upload_context: str = None  # Session-only uploaded documents
    ) -> Tuple[str, List, str, List[str], str, Dict[str, int]]:
        """
        Process query with optional additional search rounds.
        """
        from src.config.depth_presets import get_depth_preset
        
        preset = get_depth_preset(depth)
        search_params = preset.get("search_params", {})
        all_contexts = []
        all_results = []
        
        # Round 1: Initial search
        if status_callback:
            status_callback("🔍 Round 1: Initial broad search...")
            
        initial_context, initial_results, initial_refs, doi_map, _ = self._do_search(
            query, preset, model, paper_range, depth=depth, search_params=search_params,
            user_id=user_id, knowledge_source=knowledge_source
        )
        
        self.search_history.append(SearchRound(
            round_number=1,
            query=query,
            context=initial_context[:500] + "...",
            result_count=len(initial_results)
        ))
        
        all_contexts.append(initial_context)
        all_results.extend(initial_results)
        current_refs = initial_refs
        current_doi_map = doi_map
        
        # Check if LLM wants more searches
        if self.enable_reflection and self.max_rounds > 1:
            if status_callback:
                status_callback("🤔 Analyzing initial context...")
            
            # FORCE REFLECTION if significantly under-cited (e.g. < 5 papers found)
            unique_initial_dois = len(doi_map)
            
            if status_callback:
                status_callback(f"🤔 Analyzing context from {unique_initial_dois} papers...")
            
            # H4 FIX: Force hierarchical follow-up for High depth regardless of paper count
            # M2 FIX: Unify reflection thresholds from preset (was hardcoded 8/12)
            min_papers_for_follow_up = min(12, preset.get("min_unique_papers", 25) // 2)
            force_follow_up = unique_initial_dois < min_papers_for_follow_up or depth == "High"
            
            if force_follow_up:
                reason_prefix = "High-depth hierarchical drilling" if depth == "High" else f"Only {unique_initial_dois} papers found (threshold={min_papers_for_follow_up})"
                logger.info(f"Sequential RAG: Forcing follow-up — {reason_prefix}")
                # H4: Pass results for hierarchical context-aware query generation
                follow_up_queries = self._generate_follow_up_queries(query, model, initial_results=initial_results)
                follow_up_query = follow_up_queries[0] if follow_up_queries else f"additional evidence for {query[:50]}"
                reasoning = f"{reason_prefix}. Using targeted query: {follow_up_query[:40]}..."
            else:
                follow_up_query, reasoning = self._ask_for_more_info(query, initial_context, model)
                
                # OVERRIDE: If model says SUFFICIENT but below threshold
                if not follow_up_query and unique_initial_dois < min_papers_for_follow_up * 2:
                    logger.info(f"Sequential RAG: Overriding SUFFICIENT. Papers ({unique_initial_dois}) < {min_papers_for_follow_up * 2}.")
                    follow_up_queries = self._generate_follow_up_queries(query, model, initial_results=initial_results)
                    follow_up_query = follow_up_queries[0] if follow_up_queries else f"quantitative data for {query[:50]}"
                    reasoning = f"Paper count ({unique_initial_dois}) below {min_papers_for_follow_up * 2}. Generated targeted query: {follow_up_query[:40]}..."
            
            if follow_up_query:
                logger.info(f"Sequential RAG: LLM requested follow-up: {follow_up_query}")
                
                if status_callback:
                    status_callback(f"🔄 Round 2: {reasoning[:60]}... -> Searching for \"{follow_up_query[:30]}...\"")
                
                # H4 FIX: Use 1/4 preset values for follow-up (focused micro-search)
                follow_up_params = dict(search_params) if search_params else {}
                if depth == "High":
                    follow_up_params["top_k_override"] = max(25, preset.get("top_k_initial", 100) // 4)
                    logger.info(f"Sequential RAG: Follow-up using 1/4 presets (top_k={follow_up_params['top_k_override']})")
                
                # Round 2: Follow-up search
                follow_context, follow_results, follow_refs, follow_doi_map, _ = self._do_search(
                    follow_up_query, preset, model, paper_range, depth=depth, search_params=follow_up_params,
                    user_id=user_id, knowledge_source=knowledge_source
                )
                
                self.search_history.append(SearchRound(
                    round_number=2,
                    query=follow_up_query,
                    context=follow_context[:500] + "...",
                    result_count=len(follow_results)
                ))
                
                all_contexts.append(follow_context)
                all_results.extend(follow_results)
                # Merge DOI maps and refs
                for doi, num in follow_doi_map.items():
                    if doi not in current_doi_map:
                        current_doi_map[doi] = len(current_doi_map) + 1
                current_refs.extend([r for r in follow_refs if r not in current_refs])
                
                # Log negative decision (follow-up needed)
                self.reflection_log.append({
                    "round": 1,
                    "decision": "follow_up",
                    "query": follow_up_query,
                    "reasoning": reasoning
                })
                
            else:
                 if status_callback:
                    status_callback(f"✅ Sufficient: {reasoning[:60]}...")
                 
                 # Log positive decision
                 self.reflection_log.append({
                    "round": 1,
                    "decision": "sufficient",
                    "reasoning": reasoning
                })
        
        # Generate final response
        if status_callback: # Ensure callback is checked before call
             status_callback("✍️ Synthesizing final response...")

        combined_context = "\n\n---\n\n".join(all_contexts)

        # Prepend quick upload context (session-only documents) if provided
        if quick_upload_context:
            combined_context = (
                "=== USER-PROVIDED DOCUMENTS (Highest Priority) ===\n\n"
                f"{quick_upload_context}\n\n"
                "=== RETRIEVED KNOWLEDGE BASE ===\n\n"
                f"{combined_context}"
            )
        
        # Count unique DOIs
        unique_dois_available = len(set(r.chunk.doi for r in all_results))
        
        response, confidence, compliance_badge = self._generate_response(
            query, combined_context, model, preset, conversation_history,
            citation_density=citation_density,
            auto_citation_density=auto_citation_density,
            unique_sources_available=unique_dois_available
        )
        
        sources = self._extract_sources(all_results, current_doi_map)
        
        return response, sources, confidence, current_refs, compliance_badge, current_doi_map
    
    def _generate_response(
        self,
        query: str,
        context: str,
        model: str,
        preset: dict,
        conversation_history: List[Dict] = None,
        citation_density: str = None,
        auto_citation_density: bool = True,
        unique_sources_available: int = 10
    ) -> Tuple[str, str, str]:
        """Generate final response with citation diversity instructions."""
        prompt_builder = self.pipeline["prompt_builder"]
        llm = self.pipeline["llm"]
        
        base_prompt = prompt_builder.build_rag_prompt(
            query=query,
            context=context,
            conversation_history=conversation_history or []
        )
        
        # Calculate citation targets based on available sources and density setting
        try:
            from src.utils.citation_density import calculate_citation_target
            citation_info = calculate_citation_target(
                query=query,
                depth="High",  # Sequential is always high depth
                density_level=citation_density or "Medium",
                auto_decide=auto_citation_density
            )
            target_citations = citation_info["target_citations"]
            min_citations = citation_info["min_citations"]
        except ImportError:
            # Fallback
            target_citations = max(15, int(unique_sources_available * 0.7))
            min_citations = max(10, int(unique_sources_available * 0.5))
        
        # Cap by available sources (but NOT when user explicitly wants High density)
        if auto_citation_density or citation_density != "High":
            target_citations = min(target_citations, unique_sources_available)
            min_citations = min(min_citations, int(unique_sources_available * 0.7))
        # When High density is explicitly requested, keep full target
        
        # Build citation instructions - FORCEFUL with explicit counts
        citation_instructions = f"""

⚠️ MANDATORY CITATION REQUIREMENT ⚠️
You MUST cite AT LEAST {min_citations} different papers. This is NON-NEGOTIABLE.
Target: {target_citations} unique paper citations.

CITATION RULES:
1. EVERY factual claim, statistic, or finding MUST have an inline citation.
2. Do NOT write paragraphs of facts with one citation at the end.
3. CORRECT: "Roundabouts reduce injury crashes by 75% (Gross et al., 2012), while DDIs show 60% reduction (Claros et al., 2017)."
4. WRONG: "Roundabouts are effective and DDIs also work well (Smith, 2020)."

SOURCE DIVERSITY:
- Use at least {min_citations} DIFFERENT papers (not the same 3-4 repeatedly).
- You have {unique_sources_available} papers available - USE THEM.

CITATION FORMAT:
- Use (Author, Year) or (Author et al., Year) format.
- Match author names AND years EXACTLY as shown in the context.
- DO NOT invent or modify years - copy the EXACT year from each source.
- Example: If context shows "[1] Smith, J. (2022)", you MUST write "(Smith, 2022)" NOT "(Smith, 2025)".

🚨 FINAL CHECK: Before finishing, COUNT your unique citations. If fewer than {min_citations}, GO BACK and ADD MORE citations from the available papers.
"""
        
        prompt = base_prompt + citation_instructions
        
        response = llm.generate(
            prompt=prompt,
            system_prompt=prompt_builder.system_prompt,
            temperature=preset["temperature"],
            max_tokens=preset["max_tokens"],
            model=model
        )
        
        # Validate citations and potentially regenerate
        try:
            from src.generation import validate_response, get_compliance_badge
            validation = validate_response(response, num_sources=50)
            
            # Smart regeneration: if compliance is low, retry ONCE with feedback
            if validation.compliance_score < 0.7:
                issues_str = "; ".join(validation.issues[:3]) if validation.issues else "Low citation density"
                logger.warning(f"Low citation score ({validation.compliance_score:.2f}). Regenerating...")
                
                retry_prompt = prompt + f"""

SYSTEM ALERT: Your previous response was REJECTED.
Issues: {issues_str}
You MUST cite a source for EVERY factual statement. Retry now."""
                
                response = llm.generate(
                    prompt=retry_prompt,
                    system_prompt=prompt_builder.system_prompt,
                    temperature=preset["temperature"],
                    max_tokens=preset["max_tokens"],
                    model=model
                )
                # Re-validate after retry
                validation = validate_response(response, num_sources=50)
            
            compliance_badge = get_compliance_badge(validation.compliance_score)
        except Exception:
            compliance_badge = "⚪ N/A"
        
        # Determine confidence based on unique sources (using centralized thresholds)
        from src.config.thresholds import get_confidence_level
        confidence = get_confidence_level(unique_sources_available)
        
        return response, confidence, compliance_badge
    
    def process_with_sections(
        self,
        query: str,
        depth: str,
        model: str,
        paper_range: Tuple[int, int],
        conversation_history: List[Dict] = None,
        citation_density: str = None,
        auto_citation_density: bool = True,
        preset: dict = None,
        status_callback = None,
        step_callback: callable = None,  # Live monitoring callback
        user_id: str = None  # Multi-user isolation
    ) -> Generator[GenerationProgress, None, Dict]:
        """
        Process query with section-by-section generation and streaming.
        
        Yields:
            GenerationProgress objects for real-time streaming display
            
        Returns:
            Dict with final results (response, sources, confidence, refs, etc.)
        """
        # Monitoring Wrapper
        from src.utils.monitoring import RunContext
        ctx = start_run(query, {"depth": depth, "model": model, "paper_range": str(paper_range)})
        
        # Register live monitoring callback if provided
        if step_callback:
            ctx.set_callback(step_callback)
        
        try:
            yield from self._process_with_sections_core(
                query, depth, model, paper_range,
                conversation_history, citation_density,
                auto_citation_density, preset, status_callback
            )
        finally:
            end_run()

    def _process_with_sections_core(
        self,
        query: str,
        depth: str,
        model: str,
        paper_range: Tuple[int, int],
        conversation_history: List[Dict] = None,
        citation_density: str = None,
        auto_citation_density: bool = True,
        preset: dict = None,
        status_callback = None
    ) -> Generator[GenerationProgress, None, Dict]:
        """
        Process query with section-by-section generation and streaming.
        
        Yields:
            GenerationProgress objects for real-time streaming display
            
        Returns:
            Dict with final results (response, sources, confidence, refs, etc.)
        """
        if preset is None:
            # FIX: Load actual depth preset to exclude missing keys like 'top_k_initial'
            from src.config.depth_presets import get_depth_preset
            preset = get_depth_preset(depth)
        
        final_result = {}
        
        # M4 FIX: KB size guard — prevent infinite seeking when KB is small
        try:
            vs = self.pipeline.get("hybrid_search")
            if vs and hasattr(vs, "vector_store") and hasattr(vs.vector_store, "count"):
                kb_size = vs.vector_store.count()
                min_papers = preset.get("min_unique_papers", 10)
                if kb_size < min_papers * 3:  # Rough heuristic: 3 chunks/paper average
                    estimated_papers = kb_size // 3
                    logger.warning(f"[M4] KB small: ~{estimated_papers} papers (KB chunks={kb_size}). "
                                   f"Depth '{depth}' wants min {min_papers}. Capping target.")
                    preset = dict(preset)  # Don't mutate shared preset
                    preset["min_unique_papers"] = max(3, estimated_papers)
                    yield GenerationProgress(
                        type="warning",
                        title="Knowledge Base Size",
                        content=f"⚠️ Knowledge base has ~{estimated_papers} papers. "
                                f"Adjusted target from {min_papers} to {preset['min_unique_papers']}.\n\n",
                        section_num=0,
                        total_sections=0,
                    )
        except Exception as e:
            logger.debug(f"[M4] KB size check failed (non-fatal): {e}")
        
        # Step 1: Initial broad search to understand available sources
        if status_callback:
            status_callback("🔍 Initial research scan...")
        
        # H9 FIX: Capture reranked_results for landscape + per-section injection
        initial_context, initial_results, initial_refs, initial_doi_map, initial_reranked = self._do_search(
            query, preset, model, paper_range, depth=depth, user_id=user_id
        )
        num_sources = len(initial_doi_map)
        
        if status_callback:
            status_callback(f"📊 METRICS: Found {num_sources} unique papers from {len(initial_results)} chunks")
        
        logger.info(f"Initial search found {num_sources} unique sources")
        
        # Step 2: Resolve paper target and orchestrate sections
        from src.config.depth_presets import resolve_paper_target
        # H5 FIX: Explicit logging for let_ai_decide (currently hardcoded True — no sidebar control wired)
        let_ai_decide = True  # TODO: Wire to sidebar checkbox when available
        logger.info(f"[CONFIG] Let AI Decide: {let_ai_decide} | Depth: {depth} | Paper Range: {paper_range}")
        target_papers, _, _ = resolve_paper_target(depth, paper_range, let_ai_decide=let_ai_decide)
        
        if status_callback:
            status_callback("🗺️ Mapping knowledge landscape...")

        # Generate Knowledge Map from Phase 1 results
        topic_landscape = None
        with DiagnosticGate(
            "Knowledge Landscape", 
            severity="warning",
            context={"query": query}, # Changed from initial_query to query
            suppress=True # Allow proceeding without landscape
        ) as gate:
            try:
                # Use top 150 results for High, 75 for Medium
                max_results_map = 150 if depth == "High" else 75
                # H9 FIX: Use full reranked results for landscape (not starved context survivors)
                topic_landscape = self._generate_topic_landscape(
                    results=initial_reranked if initial_reranked else initial_results,
                    query=query,
                    model=model,
                    max_results=max_results_map
                )
                logger.info(f"Knowledge Map generated ({len(topic_landscape)} chars)")
                gate.context["landscape_size"] = len(topic_landscape)
                
                # Heartbeat
                # Assuming topic_landscape is a string or has a similar property for size
                gate.set_success_message(f"Identified knowledge clusters ({len(topic_landscape)} chars)")
            except Exception as e:
                # CRITICAL FIX: Re-raise system interrupts (like StopException/RerunException)
                if not isinstance(e, Exception): # Catch BaseException types (interrupts)
                    raise e
                    
                logger.error(f"Failed to generate knowledge map: {e}")
                # Notify user that knowledge map failed
                yield GenerationProgress(
                    type="warning",
                    title="Knowledge Mapping",
                    content="⚠️ **Knowledge map generation failed** - Proceeding with standard planning.\n\n"
                            "The system was unable to analyze the retrieved literature to create a thematic overview "
                            "(this may occur with certain model configurations or timeouts). Planning will continue "
                            "using standard academic structure, but may lack evidence-based insights for section allocation.",
                    section_num=0,
                    total_sections=0
                )
                topic_landscape = None
                raise e # Trigger the reporting gate
            
        if status_callback:
            status_callback("🎯 Planning response structure...")
        
        # Try LLM orchestration first (with Knowledge Map)
        # Try LLM orchestration first (with Knowledge Map)
        with DiagnosticGate("Plan Orchestration", severity="warning", context={"target_papers": target_papers}) as gate:
            orchestration = self._orchestrate_sections(
                query=query,
                depth=depth,
                target_papers=target_papers,
                model=model,
                topic_landscape=topic_landscape
            )
            if orchestration:
                num_sections = len(orchestration.get("sections", []))
                gate.context["section_count"] = num_sections
                if status_callback:
                    status_callback(f"📊 METRICS: Knowledge Map generated. Plan created with {num_sections} sections.")
                sec_count = len(orchestration.get("sections", []))
                gate.set_success_message(f"Plan created with {sec_count} sections")
        

        
        # Fallback to existing methods if orchestration fails
        if orchestration is None:
            # Notify user that fallback is being used
            logger.warning("LLM orchestration failed, using fallback algorithmic planning")
            yield GenerationProgress(
                type="warning",
                title="Planning Mode",
                content="⚠️ **AI orchestration unavailable** - Using algorithmic section planning instead.\n\n"
                        "The AI was unable to generate an optimal section structure (this may occur due to "
                        "model timeouts or complex queries). The system has automatically switched to rule-based "
                        "planning, which will still produce a comprehensive response but may have less optimized "
                        "citation distribution across sections.",
                section_num=0,
                total_sections=0
            )
            orchestration = self._fallback_orchestration(query, depth, target_papers, model, num_sources)
        
        # Initialize Adaptive Token Manager (AFTER fallback to ensure correct orchestration)
        token_manager = AdaptiveTokenManager(depth=depth, orchestration=orchestration)

        # Extract section info from orchestration
        outline = [s["title"] for s in orchestration["sections"]]
        section_count = len(outline)
        
        # Check for complexity warning
        try:
            from src.utils.citation_density import assess_question_complexity
            complexity = assess_question_complexity(query)
            if complexity == "complex" and depth == "Low":
                yield GenerationProgress(
                    type="warning",
                    title="",
                    content="⚠️ Complex question with Low depth may limit analysis depth.",
                    section_num=0,
                    total_sections=section_count
                )
        except ImportError:
            pass
        
        # Step 3: Show outline
        if status_callback:
            status_callback(f"📝 Planning {section_count} sections...")
        
        yield GenerationProgress(
            type="outline",
            title="Research Outline",
            content="\n".join(f"• {s}" for s in outline),
            section_num=0,
            total_sections=section_count
        )
        
        # Step 4: Generate each section with dedicated search
        section_results = []
        all_results = list(initial_results)
        all_doi_map = dict(initial_doi_map)
        all_refs = list(initial_refs)
        all_reranked_pool = list(initial_reranked if initial_reranked else initial_results)  # P5: Full reranked pool for reference aggregation
        
        # M3 FIX: Integrate AdaptiveDepth for search parameter tuning
        try:
            from src.retrieval.adaptive_depth import get_adaptive_params
            from src.retrieval.question_classifier import classify_question
            query_type = classify_question(query)
            initial_confidence = len(initial_doi_map) / max(1, preset.get("min_unique_papers", 25))
            adaptive = get_adaptive_params(query_type, min(1.0, initial_confidence), depth)
            logger.info(f"[M3] AdaptiveDepth: type={query_type}, confidence={initial_confidence:.2f}, "
                       f"expansion={adaptive.search_expansion}, mode={adaptive.reflection_mode}, "
                       f"desc='{adaptive.description}'")
        except Exception as e:
            logger.debug(f"[M3] AdaptiveDepth skipped (non-fatal): {e}")
        
        # Track covered points to avoid redundancy
        covered_points = []
        
        # DEFERRED FINAL SECTION: Check if last section should be deferred
        # Final sections (Conclusion, Summary, etc.) are generated AFTER proofreading
        deferred_final_section = None
        sections_to_generate = orchestration["sections"]
        
        # Check if the last section matches final section patterns
        if sections_to_generate and is_final_section(sections_to_generate[-1]["title"]):
            deferred_final_section = sections_to_generate[-1]
            sections_to_generate = sections_to_generate[:-1]  # Exclude final section from main loop
            logger.info(f"Deferring final section: {deferred_final_section['title']}")
        
        for i, section_plan in enumerate(sections_to_generate):
            section_title = section_plan["title"]
            section_citations = section_plan["citations"]
            search_focus = section_plan.get("focus", f"{section_title} {query}")
            
            if status_callback:
                status_callback(f"✍️ Writing section {i+1}/{section_count}: {section_title}...")
            
            # Section-specific search: FULL database search for each section
            # This is ESSENTIAL for finding new papers that the initial query missed
            # Each section's focus query discovers different relevant papers
            # IMPROVEMENT: Inject Phase 1 results to ensure global context is preserved/reranked
            # Get limits for this section
            limits = token_manager.get_section_limits(i, section_citations)
            
            # Create section-specific context builder with dynamic limits
            section_context_builder = ContextBuilder(
                max_context_tokens=limits["max_context_tokens"],
                chars_per_token=4.0,
                deduplicate=True
            )

            # 2. Search for this section
            section_query = search_focus
            with DiagnosticGate(
                "Section Search", 
                severity="warning",
                context={"section": section_plan.get("title")},
                suppress=True # Fallback to initial context
            ) as gate:
                try:
                    section_context, section_search_results, section_refs, section_doi_map, section_reranked = self._do_search(
                        section_query, preset, model, paper_range,
                        inject_results=initial_reranked if initial_reranked else initial_results,  # H9: inject full reranked set
                        context_builder=section_context_builder,
                        max_per_doi=3,  # Force diversity to prevent single-paper domination
                        user_id=user_id
                    )
                    gate.context["hits"] = len(section_search_results)
                    unique_sec_docs = len({r.chunk.doi for r in section_search_results}) if section_search_results else 0
                    gate.set_success_message(f"Section '{section_title}' context: {len(section_search_results)} chunks from {unique_sec_docs} papers")
                except Exception as e:
                    # CRITICAL FIX: Re-raise system interrupts
                    if not isinstance(e, Exception): 
                        raise e
                        
                    logger.warning(f"Section search failed: {e}, using initial context")
                    section_context = initial_context
                    section_search_results = initial_results
                    section_refs = initial_refs
                    section_doi_map = initial_doi_map
                    section_reranked = None  # P5: No reranked pool in fallback case
                    raise e # Trigger gate reporting
            
            # Build previous summary for redundancy avoidance
            previous_summary = "\n".join(f"- {p}" for p in covered_points) if covered_points else ""
            
            # Generate section content
            with StepTracker(f"Section {i+1} Generation") as tracker:
                tracker.log_input("title", section_title)
                tracker.log_input("focus_query", section_query)
                tracker.log_input("context_length", len(section_context))
                tracker.log_metadata("available_sources", len(section_doi_map))
                
                section = None # Initialize to handle suppression fallback
                with DiagnosticGate("Section Writing", severity="error", context={"title": section_title}, suppress=True) as gate:
                    # EVIDENCE-FIRST ARCHITECTURE (V2)
                    # Replace legacy prompt-and-pray with Graph of Claims workflow
                    try:
                        gen = self.academic_engine.generate_section_v2(
                            section_title=section_title,
                            retrieval_results=section_search_results,
                            query=query,
                            section_num=i+1,
                            total_sections=section_count,
                            review_text=section_plan.get("abstract", "")
                        )
                        # Bubble up progress events
                        section = yield from gen
                        
                    except Exception as e:
                        logger.error(f"V2 Generation failed: {e}")
                        raise e

                    gate.context["content_len"] = len(section.content)
            
            # Handle Section Writing Failure (Fallback)
            if section is None:
                logger.error(f"Section {i+1} generation failed (suppressed). Creating placeholder.")
                # M5 FIX: Yield diagnostic warning to UI so user can see gate suppression
                yield GenerationProgress(
                    type="warning",
                    title=f"Section {i+1} Failed",
                    content=f"⚠️ **'{section_title}'** generation failed (timeout/context limit). Using placeholder.\n\n",
                    section_num=i+1,
                    total_sections=section_count,
                )
                from src.retrieval.sequential.models import SectionResult # Ensure import if not at top
                section = SectionResult(
                    title=section_title,
                    content="⚠️ **Section Generation Failed**\n\nThe AI model failed to generate this section due to a technical error (likely timeout or context limit).",
                    citations_used=[]
                )




            tracker.log_output("content_length", len(section.content))
            tracker.log_output("citations_used", len(section.citations_used))
            
            # Extract key points for next section's redundancy tracking
            section_key_points = self._extract_key_points(section.content)
            covered_points.extend(section_key_points)
            
            # Attach references and DOIs to section result
            section.apa_references = section_refs
            section.doi_set = set(section_doi_map.keys())
            # doi_map values are citation numbers (int), not dicts
            section.sources = [{"doi": doi, "citation_num": num} for doi, num in section_doi_map.items()]
            
            section_results.append(section)
            
            all_results.extend(section_search_results)
            all_doi_map.update(section_doi_map)
            all_refs.extend(section_refs)
            # P5: Accumulate ALL reranked results for full-pool reference aggregation
            if section_reranked:
                all_reranked_pool.extend(section_reranked)
            
            # Stream section to UI
            yield GenerationProgress(
                type="section",
                title=section_title,
                content=section.content,
                section_num=i + 1,
                total_sections=section_count
            )
            
            if status_callback:
                status_callback(f"📊 METRICS: Section {i+1} generated ({len(section.content)} chars).")
        
        # Step 5: Aggregate and deduplicate references
        unique_refs = []
        unique_dois = []
        with DiagnosticGate("Reference Aggregation", severity="warning", suppress=True) as gate:
            unique_refs, unique_dois = self._aggregate_references(section_results, all_reranked_pool)
            gate.context["unique_count"] = len(unique_dois)
            gate.set_success_message(f"Aggregated {len(unique_dois)} unique references")
            
        if status_callback:
            status_callback(f"📊 METRICS: Aggregated {len(unique_dois)} unique references.")
            
        unique_count = len(unique_dois)
        
        # Step 6: Combine sections into full response
        full_response = ""
        for section in section_results:
            full_response += f"\n\n## {section.title}\n\n{section.content.lstrip()}"
        full_response = full_response.strip()
        
        # Step 7: Proofreading pass - polish the response
        if status_callback:
            status_callback("📝 Multi-pass proofreading...")
        
        with StepTracker("Proofreading"):
            # SAFEGUARD: Proofreading crash should not kill the report
            proofreading_notes = []
            with DiagnosticGate("Proofreading", severity="error", suppress=True) as gate:
                full_response, proofreading_notes = self._proofread_response(
                    response=full_response,
                    apa_references=unique_refs,
                    model=model,
                    preset=preset,
                    status_callback=status_callback,
                    token_manager=token_manager
                )

        if status_callback:
            status_callback(f"📊 METRICS: Proofreading complete. {len(proofreading_notes)} notes generated.")
        
        # DEFERRED FINAL SECTION: Generate after proofreading completes
        # This ensures the summary/conclusion reflects the finalized, cleaned content
        if deferred_final_section:
            if status_callback:
                status_callback(f"✨ Writing {deferred_final_section['title']}...")
            
            # Build source list for citations
            source_list = "\n".join([
                f"- {ref}" for ref in unique_refs[:30]  # Top 30 refs for context
            ])
            
            with StepTracker("Final Section Generation"):
                # SAFEGUARD: Final section crash should not kill report
                final_content = ""
                with DiagnosticGate("Final Section", severity="error", suppress=True) as gate:
                    final_content = self._generate_final_section(
                        final_title=deferred_final_section["title"],
                        proofread_content=full_response,
                        query=query,
                        source_list=source_list,
                        target_citations=deferred_final_section.get("citations", 5),
                        model=model,

                        preset=preset,
                        max_tokens=token_manager.get_section_limits(0, 5)["max_output_tokens"] # Use generic limit for final section
                    )
                    gate.context["char_count"] = len(final_content)
                    gate.set_success_message(f"Final Section generated ({len(final_content)} chars)")
            
            # Append to response (NO proofreading for final section - it's based on clean content)
            full_response += f"\n\n## {deferred_final_section['title']}\n\n{final_content}"
            
            logger.info(f"Final section appended: {deferred_final_section['title']}")
        
        # Step 7.5: Append formatted references to response
        # P9 FIX: Use DOI-based splitting (deterministic, no name parsing)
        all_cited_dois = set()
        for section in section_results:
            all_cited_dois.update(section.cited_dois)
        logger.info(f"P9: Collected {len(all_cited_dois)} cited DOIs across {len(section_results)} sections")
        
        cited_refs, uncited_refs = split_references_by_doi(unique_refs, all_cited_dois)
        formatted_refs = format_split_references(cited_refs, uncited_refs)
        
        # Append to response (before proofreading notes)
        full_response += f"\n\n---\n\n## References\n\n{formatted_refs}"
        logger.info(f"Appended {len(cited_refs)} cited and {len(uncited_refs)} uncited references")
        
        if status_callback:
            status_callback(f"📊 METRICS: Final Assembly. Cited: {len(cited_refs)}, Additional: {len(uncited_refs)}.")
        
        # Append proofreading notes as footnote if any errors occurred
        if proofreading_notes:
            notes_text = "\n\n---\n" + "\n".join(proofreading_notes)
            # Store notes for later (don't add to main response yet)
            self._proofreading_notes = proofreading_notes
        else:
            self._proofreading_notes = []
        
        # Step 7: Validate citations and compute metrics
        try:
            from src.generation import validate_response, get_compliance_badge
            with DiagnosticGate("Citation Compliance", severity="warning") as gate:
                validation = validate_response(full_response, len(unique_refs))
                gate.context["score"] = validation.compliance_score
                gate.set_success_message(f"Compliance Check: {validation.compliance_score*100:.0f}%")
            compliance_badge = get_compliance_badge(validation.compliance_score)
        except ImportError:
            compliance_badge = "Good" if unique_count >= 10 else "Fair"
        
        # Confidence based on unique papers (using centralized thresholds)
        from src.config.thresholds import get_confidence_level
        confidence = get_confidence_level(unique_count)
        
        # Step 8: Build sources list
        sources = self._extract_sources(all_results, all_doi_map)
        
        # Include proofreading notes as footnote if any
        response_with_notes = full_response
        
        # Include proofreading notes as footnote if any
        
        if self._proofreading_notes:
            response_with_notes += "\n\n---\n" + "\n".join(self._proofreading_notes)
        
        # Store final result
        final_result = {
            "response": response_with_notes,
            "sources": sources,
            "confidence": confidence,
            "apa_references": unique_refs,
            "compliance_badge": compliance_badge,
            "doi_map": all_doi_map,
            "section_count": section_count,
            "unique_papers": unique_count,
            "proofreading_notes": self._proofreading_notes
        }
        
        # CRITICAL FIX: Update state BEFORE yielding 'complete'
        # The UI reads this immediately upon receiving the event
        self._last_result = final_result
        
        # Yield completion
        yield GenerationProgress(
            type="complete",
            title="Complete",
            content=response_with_notes,
            section_num=section_count,
            total_sections=section_count
        )
        
        return final_result
        



def create_sequential_rag(pipeline: dict, max_rounds: int = 2) -> SequentialRAG:
    """Factory function to create SequentialRAG."""
    return SequentialRAG(pipeline, max_rounds=max_rounds)
