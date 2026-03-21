"""
Planning Mixin for Sequential RAG.

Section planning and orchestration capabilities:
- Section count determination
- Topic landscape/knowledge map generation
- LLM-based orchestration for unified section planning
- Validation and fallback mechanisms
"""

import re
import json
import logging
from typing import List, Dict, Tuple, Optional
from math import ceil

from src.utils.monitoring import StepTracker

logger = logging.getLogger(__name__)


class PlanningMixin:
    """
    Mixin providing section planning and orchestration capabilities.
    
    Requires:
        - self.pipeline with "llm" key
    """
    
    def _determine_section_count(
        self,
        query: str,
        depth: str,
        num_sources: int
    ) -> Tuple[int, Optional[str]]:
        """
        Determine section count based on depth and query complexity.
        
        Args:
            query: User's question
            depth: "Low", "Medium", "High"
            num_sources: Number of available sources
            
        Returns:
            Tuple of (section_count, optional_warning_message)
        """
        try:
            from src.utils.citation_density import assess_question_complexity
            complexity = assess_question_complexity(query)
        except ImportError:
            complexity = "moderate"
        
        # Base counts by depth
        base = {"Low": 2, "Medium": 3, "High": 5}
        max_by_depth = {"Low": 3, "Medium": 4, "High": 6}
        
        count = base.get(depth, 3)
        warning = None
        
        # Handle complexity mismatch
        if complexity == "complex" and depth == "Low":
            warning = "⚠️ Complex question with Low depth may limit analysis depth."
        elif complexity == "simple" and depth == "High":
            count = min(count + 1, max_by_depth[depth])
        elif complexity == "complex" and depth == "High":
            count = max_by_depth[depth]
        
        # Adjust if few sources
        if num_sources > 0 and num_sources < count * 3:
            count = max(2, num_sources // 3)
        
        logger.info(f"Section count determined: {count} (depth={depth}, complexity={complexity}, sources={num_sources})")
        return count, warning
    
    def _generate_topic_landscape(
        self,
        results: List[Dict],
        query: str,
        model: str,
        max_results: int = 50
    ) -> str:
        """
        Generate a thematic 'Knowledge Map' from Phase 1 search results.
        
        This analyzes the actual retrieved literature to identify:
        1. Key clusters/topics present (Evidence)
        2. Volume of evidence for each
        3. Missing areas (Gaps)
        
        Args:
            results: List of search result dictionaries
            query: User's original query
            model: LLM model to use
            max_results: Max results to analyze (token limit protection)
            
        Returns:
            String description of the topic landscape
        """
        logger.info(f"Generating Knowledge Map from top {min(len(results), max_results)} results...")
        
        # 1. Prepare snippets
        snippets = []
        for i, res in enumerate(results[:max_results]):
            # Handle RetrievalResult objects which are not dicts
            try:
                # If res is a RetrievalResult object (has 'chunk' attribute)
                if hasattr(res, 'chunk'):
                    title = getattr(res.chunk, 'title', 'Untitled')
                    year = getattr(res.chunk, 'year', 'n.d.')
                    content = getattr(res.chunk, 'content', '')
                # If res is a dict (fallback)
                elif isinstance(res, dict):
                    title = res.get('title', 'Untitled')
                    year = res.get('year', 'n.d.')
                    content = res.get('snippet', res.get('content', ''))
                # If res is something else (unexpected)
                else:
                    title = getattr(res, 'title', 'Untitled')
                    year = getattr(res, 'year', 'n.d.')
                    content = getattr(res, 'content', '')
            except Exception as e:
                logger.warning(f"Error extracting snippet from result {i}: {e}")
                continue

            # Use snippet or first 300 chars of content
            text = content[:300].replace('\n', ' ')
            snippets.append(f"[{i+1}] {title} ({year}): {text}...")
            
        snippets_text = "\n".join(snippets)
        
        # 2. LLM Analysis
        prompt = f"""Analyze the search results below for the query: "{query}"

SEARCH FINDINGS:
{snippets_text}

TASK: Create a 'Knowledge Map' summary of the available literature.
1. Identify 3-5 distinct thematic clusters or methodologies found in these papers.
2. Estimate the volume of evidence for each (High/Medium/Low).
3. Identify standard topics that seem MISSING from these results (Potential Gaps).

CRITICAL CONSTRAINTS:
- Base your analysis ONLY on the snippets provided above
- Do NOT invent topics, papers, or citations not shown in the snippets
- Do NOT reference papers by specific years unless extracting from the snippets
- Focus on describing what evidence IS available, not what you think should exist

OUTPUT FORMAT:
- Cluster: [Name] (Evidence: High/Med/Low) - Summary of findings...
- Cluster: [Name] (Evidence: High/Med/Low) - Summary of findings...
...
- Missing/Gaps: [Topic A], [Topic B] (Standard topics not found in retrieved set)
"""
        
        llm = self.pipeline["llm"]
        
        with StepTracker("Knowledge Map") as tracker:
            tracker.log_input("snippets_count", len(snippets))
            tracker.log_input("prompt_excerpt", prompt[:200])
            
            try:
                landscape = llm.generate(
                    prompt=prompt,
                    system_prompt="You are a senior literature review analyst. Synthesize the research landscape.",
                    temperature=0.1,
                    max_tokens=10000,
                    model=model
                )
                tracker.log_output("landscape_length", len(landscape))
                return landscape.strip()
            except Exception as e:
                logger.warning(f"Knowledge Map generation failed: {e}")
                return "Knowledge Map generation failed. Proceed with standard planning."

    def _orchestrate_sections(
        self,
        query: str,
        depth: str,
        target_papers: int,
        model: str,
        topic_landscape: str = None
    ) -> dict:
        """
        LLM-based orchestration for unified section planning.
        
        Consolidates 3 decisions into 1 LLM call:
        1. Section count
        2. Section titles
        3. Per-section unique citation allocation
        
        Args:
            query: User's research question
            depth: "Low", "Medium", or "High"
            target_papers: Total unique citations target
            model: LLM model to use
            topic_landscape: Optional Knowledge Map
            
        Returns:
            dict with structure:
            {
                "sections": [
                    {"title": str, "citations": int, "focus": str},
                    ...
                ]
            }
            Returns None if LLM fails (triggers fallback).
        """
        llm = self.pipeline["llm"]
        
        prompt = f"""You are a research orchestrator planning an academic response structure.

QUERY: "{query}"
DEPTH: {depth}
TARGET PAPERS: {target_papers}

TASK: Plan the section structure and unique citation allocation for a comprehensive research response.

CRITICAL INSTRUCTIONS:
1. **Honor User Constraints:** If the user asks for specific comparisons ("X vs Y"), timelines, or dedicated sections (e.g., "Recommendations", "Conclusion"), you MUST include them as dedicated sections. Place them **logically** in the narrative flow (e.g., Recommendations at the end), not just at the top.

2. **Hybrid Structure Strategy:**
   - **Grounding:** Use the AVAILABLE EVIDENCE (Knowledge Map) below to create sections for topics we know exist.
   - **Completeness:** If the Knowledge Map misses a standard academic topic (e.g., "Theoretical Framework", "Policy Implications") that *should* be there, **ADD IT** to the plan. Do not let the initial search limit the scope (avoid "filter bubble").
   - **Balance:** Do not rely solely on the Map. Use it to *inform* the structure, not *limit* it.

AVAILABLE EVIDENCE (Knowledge Map):
{topic_landscape if topic_landscape else "No specific map available. Plan based on standard academic structure."}

ALLOCATION RULES:
1. Section count: 2-8 sections
   - Low depth: 2-3 sections
   - Medium depth: 3-5 sections
   - High depth: 5-8 sections
   - OVERRIDE: If query asks for "comprehensive review", "systematic review", "all sources", OR if the Knowledge Map reveals rich diverse clusters, plan 5-8 sections regardless of Depth.

2. Unique citation distribution:
   - Each section needs minimum 3 unique citations
   - Total unique citations must be >= {target_papers}
   - Note: If the same source is cited multiple times, it counts as ONE unique citation

3. Section types and typical unique citation needs:
   - Introduction/Overview: 3-6 unique citations (context setting)
   - Analytical/Comparative sections: 10-20 unique citations (core evidence)
   - Methodology sections: 5-10 unique citations (technical details)
   - Conclusion: 3-8 unique citations (synthesis)

4. Focus query:
   - Each section needs a "focus" search query (specific natural language question)
   - Example: "What are the limitations of crash-based safety models?" NOT "crash based limitations models"
   - This determines the quality of evidence found for the section

CONSTRAINTS:
- Return ONLY valid JSON, no markdown, no code blocks, no explanation
- Sum of all unique citations must be >= {target_papers}
- Each section must have: title, citations (meaning unique citations), focus

OUTPUT FORMAT (exactly this structure):
{{
  "sections": [
    {{"title": "Section Title", "citations": N, "focus": "search query terms"}},
    ...
  ]
}}"""

        system_prompt = """You are a deterministic research planner. Your role is to create structured, consistent research outlines.

CRITICAL RULES:
1. Return ONLY valid JSON - no markdown, no explanations
2. Follow unique citation allocation rules exactly
3. Ensure total unique citations meet the target
4. Be consistent - similar queries should produce similar structures
5. Focus queries should be specific and searchable
6. "citations" means unique citations - same source cited multiple times = 1"""

        with StepTracker("Orchestration") as tracker:
            tracker.log_input("depth", depth)
            tracker.log_input("target_papers", target_papers)
            tracker.log_input("has_knowledge_map", bool(topic_landscape))
            
            try:
                response = llm.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=0.0,  # Maximum determinism
                    max_tokens=15000,
                    model=model
                )
                tracker.log_output("raw_response_length", len(response))
                
                # Robust JSON extraction using regex
                json_match = re.search(r'(\{.*\})', response, re.DOTALL)
                
                if json_match:
                    clean_response = json_match.group(1)
                else:
                    # Fallback: try stripping markdown code blocks manually
                    clean_response = response.strip()
                    if clean_response.startswith("```"):
                         clean_response = clean_response.split("```")[1]
                         if clean_response.startswith("json"):
                             clean_response = clean_response[4:]
                    clean_response = clean_response.strip()
                
                result = json.loads(clean_response)
                tracker.log_output("parsed_sections", len(result.get("sections", [])))
                
                # Validate and fix
                validated = self._validate_orchestration(result, target_papers, depth)
                if validated:
                    logger.info(f"LLM orchestration successful: {len(validated['sections'])} sections")
                    return validated
                else:
                    logger.warning("LLM orchestration validation failed")
                    return None
                    
            except Exception as e:
                logger.warning(f"LLM orchestration failed: {e}")
                logger.warning(f"Failed Response Content: {response if 'response' in locals() else 'No Response'}")
                return None
    
    def _validate_orchestration(self, result: dict, target: int, depth: str = "Medium") -> dict:
        """
        Validate and fix orchestration output with dynamic limits based on depth.
        
        Args:
            result: LLM output parsed as dict
            target: Target total unique citations
            depth: Research depth (Low/Medium/High)
            
        Returns:
            Validated/fixed result dict, or None to trigger fallback
        """
        # 1. Check JSON structure
        if not isinstance(result, dict) or "sections" not in result:
            logger.warning("Orchestration failed: invalid structure")
            return None
        
        sections = result["sections"]
        
        # 2. Check each section has required fields (PRE-PROCESSING)
        for i, section in enumerate(sections):
            if "title" not in section:
                section["title"] = f"Section {i+1}"
            if "citations" not in section:
                section["citations"] = 5  # unique citations
            if "focus" not in section:
                section["focus"] = section["title"]
            if "abstract" not in section:
                # Fallback if LLM provides no abstract
                section["abstract"] = f"Comprehensive analysis of {section['title']} focusing on {section['focus']}."
            
            # Enforce minimum unique citations per section
            section["citations"] = max(3, int(section["citations"]))

        # 3. Check section count (Dynamic Limits)
        count = len(sections)
        
        # Define limits per depth
        limits = {
            "Low": 3,
            "Medium": 5,
            "High": 8
        }
        max_expected = limits.get(depth, 5)
        soft_limit_max = max_expected + 2
        
        # Case A: Too few (Critical Failure)
        if count < 2:
            logger.warning(f"Orchestration failed: too few sections ({count})")
            return None
            
        # Case B: Ideal Range
        elif count <= max_expected:
            pass  # Accept
            
        # Case C: Soft Limit -> Warn but Accept
        elif count <= soft_limit_max:
            logger.warning(f"Orchestration exceeded ideal range ({count}/{max_expected}) for {depth}. Accepting as Soft Limit.")
            
        # Case D: Hard Limit -> Condense to Max Expected
        else:
            logger.warning(f"Orchestration exceeded hard limit ({count} > {soft_limit_max}). Condensing to {max_expected}...")
            sections = self._condense_sections(sections, max_sections=max_expected)
            result["sections"] = sections
            logger.info(f"Condensed to {len(sections)} sections")
        
        # 4. Check total meets target
        total = sum(s["citations"] for s in sections)
        if total < target:
            # Scale up proportionally
            scale = target / total
            for section in sections:
                section["citations"] = ceil(section["citations"] * scale)
            logger.info(f"Scaled citations: {total} → {sum(s['citations'] for s in sections)}")
        
        return result

    def _condense_sections(self, sections: List[Dict], max_sections: int = 8) -> List[Dict]:
        """
        Iteratively merge shortest adjacent sections until count <= max_sections.
        """
        while len(sections) > max_sections:
            # Find index of adjacent pair with fewest combined citations
            best_pair_idx = -1
            min_pair_score = float('inf')
            
            for i in range(len(sections) - 1):
                score = sections[i]["citations"] + sections[i+1]["citations"]
                if score < min_pair_score:
                    min_pair_score = score
                    best_pair_idx = i
            
            if best_pair_idx == -1:
                break
                
            # Merge i and i+1
            s1 = sections[best_pair_idx]
            s2 = sections[best_pair_idx + 1]
            
            merged = {
                "title": f"{s1['title']} & {s2['title']}",
                "title": f"{s1['title']} & {s2['title']}",
                "focus": f"{s1['focus']} AND {s2['focus']}",
                "abstract": f"{s1.get('abstract', '')} {s2.get('abstract', '')}",
                "citations": s1["citations"] + s2["citations"]
            }
            
            # Replace the pair with the merged section
            sections[best_pair_idx : best_pair_idx + 2] = [merged]
            
        return sections
    
    def _fallback_orchestration(self, query: str, depth: str, target: int, model: str, num_sources: int) -> dict:
        """
        Use existing methods if LLM orchestration fails.
        
        Args:
            query: User's research question
            depth: Investigation depth
            target: Target unique citations
            model: LLM model
            num_sources: Number of available sources
            
        Returns:
            Orchestration-format dict built from existing methods
        """
        logger.info("Using fallback orchestration (existing methods)")
        
        # Use existing section count determination
        section_count, _ = self._determine_section_count(query, depth, num_sources)
        
        # Use existing outline generation
        titles = self._generate_outline(query, section_count, model)
        
        # Use algorithmic citation distribution
        per_section = max(3, ceil(target / section_count))
        
        # Build result in orchestrator format
        return {
            "sections": [
                {
                    "title": title,
                    "citations": per_section,
                    "focus": f"{title} {query}",
                    "abstract": f"Detailed discussion of {title} in the context of {query}."
                }
                for title in titles
            ]
        }
    
    def _generate_outline(
        self,
        query: str,
        section_count: int,
        model: str
    ) -> List[str]:
        """
        Generate dynamic outline with specified number of sections.
        
        Returns:
            List of section titles
        """
        llm = self.pipeline["llm"]
        
        prompt = f"""You are creating an outline for a research response.

Question: "{query}"

Generate EXACTLY {section_count} section titles for a comprehensive answer.
Include these types of sections as appropriate:
- Introduction/Overview
- Analysis of key topics
- Comparison/Synthesis (if comparing topics)
- Conclusion

Return ONLY the section titles, one per line, no numbering or bullets:"""

        response = llm.generate(
            prompt=prompt,
            system_prompt="You are an academic outline generator. Return only section titles.",
            temperature=0.3,
            max_tokens=5000,
            model=model
        )
        
        sections = [s.strip() for s in response.strip().split("\n") if s.strip() and len(s.strip()) > 3]
        
        # Ensure we have the right count
        if len(sections) < section_count:
            if "Conclusion" not in sections[-1] if sections else True:
                sections.append("Conclusion")
        elif len(sections) > section_count:
            sections = sections[:section_count]
        
        logger.info(f"Generated outline: {sections}")
        return sections
