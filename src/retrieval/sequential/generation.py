"""
Generation Mixin for Sequential RAG.

Section content generation capabilities:
- Single section generation with citation requirements
- Citation extraction and validation
- Section completeness checking
- Final section (conclusion) generation
- Reference aggregation
"""

import re
import logging
from typing import List, Dict, Tuple, Set

from .models import SectionResult
from src.utils.diagnostics import report_diagnostic

logger = logging.getLogger(__name__)


class GenerationMixin:
    """
    Mixin providing section generation capabilities.
    
    Requires:
        - self.pipeline with "llm", "reranker", "context_builder" keys
    """
    
    def _generate_section(
        self,
        section_title: str,
        section_context: str,
        query: str,
        min_citations: int,
        model: str,
        preset: dict,
        available_sources: int = 10,
        previous_summary: str = "",
        max_tokens: int = 1500,
        valid_citations: List[str] = None  # NEW: Explicit list of valid citations
    ) -> SectionResult:
        """
        Generate a single section with mandatory citation quota.
        
        Args:
            section_title: Title of this section
            section_context: Retrieved context for this section
            query: Original user query
            min_citations: Minimum citations required
            model: LLM model to use
            preset: Generation preset
            available_sources: Number of sources in context
            previous_summary: Summary of points already covered (to avoid redundancy)
            valid_citations: List of valid (Author, Year) strings for strict grounding
            
        Returns:
            SectionResult with content and citation data
        """
        llm = self.pipeline["llm"]
        
        # Build redundancy avoidance section
        redundancy_instruction = ""
        if previous_summary:
            redundancy_instruction = f"""
ALREADY COVERED (do NOT repeat these points):
{previous_summary}

"""
        
        # NEW: Build "Closed Book" Citation Menu
        valid_citations_list = ""
        if valid_citations:
            # Format as a numbered list for clear selection
            valid_citations_list = "VALID SOURCES (You may ONLY cite these):\n" + "\n".join([f"[{i+1}] {ref}" for i, ref in enumerate(valid_citations)])

        prompt = f"""Write the "{section_title}" section for a research response.

ORIGINAL QUESTION: {query}

CONTEXT (from {available_sources} research papers):
{section_context}
{redundancy_instruction}

{valid_citations_list}

⚠️ MANDATORY CITATION REQUIREMENT ⚠️
You MUST cite at least {min_citations} DIFFERENT sources in this section.
Use (Author, Year) or (Author et al., Year) format matching the VALID SOURCES list above.

STRICT GROUNDING RULES:
1. You may ONLY cite papers listed in the "VALID SOURCES" section above.
2. Do NOT hallucinate citations. Do NOT cite papers mentioned inside the text if they are not in the valid list.
3. If a claim cannot be supported by a valid source, do not make the claim.

FORMATTING RULES:
- Do NOT include the section title as a header (it will be added automatically)
- Start directly with content paragraphs
- Write 2-4 focused paragraphs
- Every factual claim, statistic, or finding MUST have an inline citation
- Do NOT group all citations at the end of a paragraph
- Use diverse sources - do not over-cite the same 1-2 papers
- Ensure ALL sentences are complete - do not cut off mid-sentence or mid-citation

ACADEMIC WRITING STYLE:
- Use hedging language: "evidence suggests", "appears to", "may indicate", "research indicates"
- Avoid absolute claims; acknowledge context-dependency
- Use "compared to" rather than "superior to" when discussing interventions
- Acknowledge limitations and conditional applicability

STYLE GUIDE:
- Use American English: "roundabout" not "round-about", "signalized" not "signalised"
- Consistent terminology: CMF, AADT, EB (Empirical Bayes)
- Complete all citations with proper closing parentheses

🚨 CRITICAL: Count your citations. You need at least {min_citations} unique citations. Ensure every sentence is complete."""

        # Enhanced system prompt with style guidance
        system_prompt = """You are an academic writer producing thesis-quality research content. 
Cite sources meticulously inline. 

ETHICAL RULE: You are in strict CLOSED-BOOK mode. You may ONLY cite authors found in the 'VALID SOURCES' list provided. Attempting to cite outside this list is a critical failure.

Use hedging language for claims. 
Ensure all sentences and citations are complete - never cut off mid-thought.
Use American English spelling consistently."""

        # Retry loop for robust generation
        content = ""
        for attempt in range(2):
            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ]

                content = llm.chat(
                    messages=messages,
                    temperature=preset.get("temperature", 0.3),
                    max_tokens=max_tokens,
                    model=model
                )
                
                # Check for empty content
                if content and content.strip():
                    break # Success
                
                # Empty content handling
                msg = f"Generation attempt {attempt+1} returned empty content."
                if attempt == 0:
                    report_diagnostic(f"{msg} Retrying...", severity="warning", context={"section": section_title})
                else:
                    # Failed twice
                    raise ValueError("LLM returned empty content after retries.")
                    
            except Exception as e:
                if attempt == 0:
                    report_diagnostic(f"Generation attempt 1 failed: {e}. Retrying...", severity="warning", context={"error": str(e)})
                else:
                    raise e # Propagate to sequential_rag to trigger fallback placeholder
        
        # Post-process: Remove any duplicate header the LLM might have added
        content = self._clean_section_content(content, section_title)
        
        # Validate completeness and retry if needed
        is_complete, issue = self._validate_section_completeness(content)
        if not is_complete:
            if issue == "Empty content":
                raise ValueError("Generated content is empty after cleaning.")
                
            logger.warning(f"Section incomplete: {issue}. Requesting completion.")
            content = self._complete_truncated_section(content, llm, model, preset)
        
        # Extract citations from the generated text
        citations = self._extract_citations_from_text(content)
        
        return SectionResult(
            title=section_title,
            content=content,
            citations_used=citations,
            sources=[],
            apa_references=[],
            doi_set=set()
        )
    
    def _extract_citations_from_text(self, text: str) -> List[str]:
        """Extract citation patterns from text (parenthetical + narrative APA + numbered)."""
        citations = []
        
        # Match PARENTHETICAL (Author, Year) or (Author et al., Year)
        author_year = re.findall(r'\([A-Z][a-zA-Z\-\']+(?:\s*(?:et\s+al\.?|,?\s*&?\s*[A-Z][a-zA-Z\-]+)+)?,?\s*\d{4}\)', text)
        citations.extend(author_year)
        
        # C6 FIX: Match NARRATIVE Author (Year) or Author et al. (Year)
        narrative = re.findall(r"[A-Z][a-zA-Z\-\']+(?:\s+(?:and|&)\s+[A-Z][a-zA-Z\-\']+)?(?:\s+et\s+al\.?)?\s*\(\d{4}\)", text)
        citations.extend(narrative)
        
        # Match [N] numbered citations
        numbered = re.findall(r'\[\d+\]', text)
        citations.extend(numbered)
        
        return list(set(citations))  # Unique citations
    
    def _clean_section_content(self, content: str, section_title: str) -> str:
        """Remove duplicate section headers from content."""
        content = content.strip()
        
        # Remove various header formats the LLM might include
        patterns = [
            rf'^##?\s*{re.escape(section_title)}\s*\n+',  # ## Section Title
            rf'^{re.escape(section_title)}\s*\n+',        # Section Title (bare)
            rf'^\*\*{re.escape(section_title)}\*\*\s*\n+', # **Section Title**
        ]
        
        for pattern in patterns:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)
        
        return content.strip()
    
    def _validate_section_completeness(self, content: str) -> Tuple[bool, str]:
        """
        Check if section content ends with complete sentences.
        
        Returns:
            Tuple of (is_complete, issue_description)
        """
        content = content.strip()
        
        if not content:
            return False, "Empty content"
        
        # Patterns indicating incomplete text
        incomplete_patterns = [
            (r'\([^)]*$', "Unclosed parenthesis"),
            (r'[,;:]$', "Ends with comma/semicolon/colon"),
            (r'\bet\s+al\.?\s*$', "Ends with 'et al' without year"),
            (r'\([A-Z][a-z]+,?\s*\d{0,3}$', "Incomplete citation (missing closing paren)"),
            (r'\[[^\]]*$', "Unclosed bracket"),
            (r'\w{4,}$', "Ends without punctuation"),  # Word at end without punctuation
        ]
        
        for pattern, issue in incomplete_patterns:
            if re.search(pattern, content):
                return False, issue
        
        # Should end with proper punctuation
        if not re.search(r'[.!?)\]"]$', content):
            return False, "Does not end with proper punctuation"
        
        return True, "OK"
    
    def _complete_truncated_section(
        self,
        content: str,
        llm,
        model: str,
        preset: dict
    ) -> str:
        """Complete a truncated section by asking LLM to finish it."""
        prompt = f"""The following academic text was cut off mid-sentence or mid-citation. 
Complete it naturally with 1-2 more sentences. Ensure all parentheses and citations are properly closed.

TEXT TO COMPLETE:
{content}

INSTRUCTIONS:
- Complete the last sentence properly
- Close any open parentheses or citations
- Add 1-2 concluding sentences if appropriate
- Do NOT repeat content from earlier in the text
- Use proper citation format: (Author, Year)
- If completing a citation, use the EXACT year from the existing text - do NOT modify years


CONTINUE FROM WHERE IT WAS CUT OFF:"""

        messages = [
            {"role": "system", "content": "You are completing an academic text. Be concise and ensure proper closure."},
            {"role": "user", "content": prompt}
        ]

        continuation = llm.chat(
            messages=messages,
            temperature=0.3,
            max_tokens=1200,  # H2: was 300 (4×)
            model=model
        )
        
        # Merge content with continuation
        combined = content.rstrip() + " " + continuation.strip()
        
        return combined
    
    def _extract_key_points(self, content: str, max_points: int = 5) -> List[str]:
        """Extract key points from section content for redundancy tracking."""
        # Simple extraction: look for sentences with citations (they contain key claims)
        sentences = re.split(r'(?<=[.!?])\s+', content)
        
        key_points = []
        for sentence in sentences:
            # Sentences with citations are likely key claims
            if re.search(r'\([A-Z][a-z]+.*?\d{4}\)', sentence):
                # Truncate long sentences
                point = sentence[:100] + "..." if len(sentence) > 100 else sentence
                key_points.append(point)
                if len(key_points) >= max_points:
                    break
        
        return key_points
    
    def _rerank_for_section(
        self,
        focus_query: str,
        merged_results: List,
        merged_context: str,
        merged_refs: List[str],
        merged_doi_map: Dict[str, int],
        preset: dict,
        top_k: int = 20
    ) -> Tuple[str, List, List[str], Dict[str, int]]:
        """
        Rerank merged results for a specific section's focus query.
        
        This is a LATENCY OPTIMIZATION: Instead of performing a full database search
        for each section (which is expensive), we rerank the already-retrieved
        merged pool from Round 1+2 using the section's focus query.
        
        Args:
            focus_query: Section-specific search query
            merged_results: Combined results from all search rounds
            merged_context: Fallback context if reranking fails
            merged_refs: Fallback references
            merged_doi_map: Fallback DOI map
            preset: Depth preset for context building parameters
            top_k: Number of top results to return after reranking
            
        Returns:
            Tuple of (section_context, reranked_results, refs, doi_map)
        """
        reranker = self.pipeline.get("reranker")
        context_builder = self.pipeline.get("context_builder")
        
        # Fallback conditions: no reranker, no context builder, or insufficient results
        if not reranker or not context_builder or len(merged_results) < 10:
            logger.info(f"Rerank fallback: using merged context (results={len(merged_results)})")
            return merged_context, merged_results, merged_refs, merged_doi_map
        
        try:
            # Rerank the merged pool using section-specific focus query
            reranked = reranker.rerank(
                query=focus_query,
                results=merged_results,
                top_k=min(top_k * 2, len(merged_results))  # Get 2x top_k for context building flexibility
            )
            
            if len(reranked) < 5:
                logger.warning(f"Reranking produced too few results ({len(reranked)}), using fallback")
                return merged_context, merged_results, merged_refs, merged_doi_map
            
            # Build context from reranked results
            section_context, used_results, section_refs, section_doi_map = context_builder.build_context(
                reranked,
                max_per_doi=preset.get("max_per_doi", 3),
                min_unique_papers=5,  # Lower threshold for sections
                max_unique_papers=top_k
            )
            
            if not section_context or len(section_doi_map) < 3:
                logger.warning(f"Context building produced insufficient context, using fallback")
                return merged_context, merged_results, merged_refs, merged_doi_map
            
            logger.info(f"Section reranked: {len(section_doi_map)} papers from focus query '{focus_query[:50]}...'")
            
            return section_context, used_results, section_refs, section_doi_map
            
        except Exception as e:
            logger.warning(f"Section reranking failed: {e}, using merged context")
            return merged_context, merged_results, merged_refs, merged_doi_map
    
    def _generate_final_section(
        self,
        final_title: str,
        proofread_content: str,
        query: str,
        source_list: str,
        target_citations: int,
        model: str,
        preset: dict,
        max_tokens: int = 1500
    ) -> str:
        """
        Generate the final section (conclusion/summary) based on proofread content.
        
        This is called AFTER proofreading to ensure the summary reflects
        the finalized, cleaned content. NO proofreading is applied to this section.
        
        Args:
            final_title: Title of the final section (e.g., "Conclusions")
            proofread_content: All previous sections after proofreading
            query: Original user query
            source_list: Available sources for citation
            target_citations: Suggested citation count from orchestrator
            model: LLM model to use
            preset: Generation preset
            
        Returns:
            Generated final section content (without header)
        """
        llm = self.pipeline["llm"]
        
        # Calculate proportional target length (8-12% of content, min 200, max 800 words)
        content_word_count = len(proofread_content.split())
        target_words = max(200, min(800, int(content_word_count * 0.10)))
        
        # P18 FIX: Dynamically scale max_tokens to prevent truncation
        # 800 words * 3.5 tokens/word = 2800 tokens (well above the old 1920 limit)
        dynamic_limit = int(target_words * 3.5)
        generation_max_tokens = max(max_tokens, dynamic_limit)
        
        prompt = f"""Write the "{final_title}" section for this research response.

PROOFREAD CONTENT (all previous sections - this is the finalized content):
{proofread_content}

ORIGINAL QUESTION: {query}

AVAILABLE SOURCES (for citation if referencing specific findings):
{source_list[:3000]}

INSTRUCTIONS:
1. SYNTHESIZE the key findings from the sections above - do not simply list them
2. Provide INSIGHTFUL conclusions that go beyond summarizing  
3. Highlight implications and practical applications
4. Include actionable recommendations where appropriate
5. Match the academic writing style of the previous sections
6. Target length: approximately {target_words} words

CITATION RULES:
- Cite sources when referencing specific statistics, findings, or direct claims from the literature
- Use (Author, Year) format matching the AVAILABLE SOURCES list above
- Match author names AND years EXACTLY as shown in the AVAILABLE SOURCES list above
- DO NOT invent or modify years
- Synthesis statements and general implications may not need citations if they're your analytical conclusions

FORMATTING:
- Use hedging language: "evidence suggests", "findings indicate"
- Do NOT include the section title as a header (it will be added automatically)
- Ensure all sentences are complete

Write the {final_title} section now:"""

        system_prompt = """You are an academic writer producing a synthesis conclusion.
Be insightful, not repetitive. Focus on implications and recommendations.
Match the writing style of the provided content. Use American English."""

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]

            content = llm.chat(
                messages=messages,
                temperature=preset.get("temperature", 0.1),
                max_tokens=generation_max_tokens,
                model=model
            )
            
            # Clean any accidental header that LLM might include
            content = content.strip()
            # Remove header line if present
            if content.startswith("##"):
                lines = content.split("\n", 1)
                if len(lines) > 1:
                    content = lines[1].strip()
            
            logger.info(f"Final section generated: {len(content.split())} words for '{final_title}'")
            return content
            
        except Exception as e:
            logger.warning(f"Final section generation failed: {e}")
            return f"This section summarizes the key findings presented above regarding {query}."
    
    def _aggregate_references(
        self,
        section_results: List[SectionResult],
        full_reranked_pool: List = None
    ) -> Tuple[List[str], Set[str]]:
        """
        Aggregate and deduplicate references from all sections.
        
        P5 FIX: When full_reranked_pool is provided, collects APA references
        from ALL reranked results (not just context-selected chunks).
        This ensures the "Additional Sources" list reflects the full breadth
        of papers found during search, not just the few that fit in context.
        
        Returns:
            Tuple of (unique_apa_references, unique_dois)
        """
        seen_dois = set()
        seen_refs = set()
        unique_refs = []
        
        # Step 1: Collect from section results (these are the context-selected, cited papers)
        for section in section_results:
            seen_dois.update(section.doi_set)
            for ref in section.apa_references:
                if ref not in seen_refs:
                    seen_refs.add(ref)
                    unique_refs.append(ref)
        
        # Step 2 (P5 FIX): Collect from full reranked pool — all papers found during search
        if full_reranked_pool:
            for result in full_reranked_pool:
                doi = result.chunk.doi
                if doi and doi not in seen_dois:
                    seen_dois.add(doi)
                    # Extract APA reference from Qdrant payload metadata
                    apa_ref = result.chunk.metadata.get('apa_reference', '')
                    if not apa_ref:
                        # Fallback: construct minimal citation
                        authors = result.chunk.metadata.get('authors', 'Unknown')
                        if isinstance(authors, list):
                            authors = ', '.join(authors)
                        year = result.chunk.metadata.get('year', 'n.d.')
                        title = result.chunk.metadata.get('title', 'Untitled')
                        apa_ref = f"{authors} ({year}). {title}. https://doi.org/{doi}"
                    
                    if apa_ref not in seen_refs:
                        seen_refs.add(apa_ref)
                        unique_refs.append(apa_ref)
        
        logger.info(f"Aggregated {len(unique_refs)} unique references from {len(section_results)} sections"
                    f"{f' + {len(full_reranked_pool)} reranked pool' if full_reranked_pool else ''}")
        return unique_refs, seen_dois
