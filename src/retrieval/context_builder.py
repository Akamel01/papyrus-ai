"""
SME Research Assistant - Context Builder

Assembles retrieved chunks into context for LLM generation.
"""

import logging
from typing import List, Dict, Any, Tuple, Optional

from src.core.interfaces import RetrievalResult
from src.utils.apa_resolver import APAReferenceResolver

logger = logging.getLogger(__name__)


class ContextBuilder:
    """
    Builds context from retrieved chunks for LLM generation.
    """
    
    def __init__(
        self,
        max_context_tokens: int = 6000,
        chars_per_token: float = 4.0,
        deduplicate: bool = True,
        include_metadata: bool = True,
        db_path: Optional[str] = None
    ):
        """
        Initialize context builder.
        
        Args:
            max_context_tokens: Maximum tokens in context
            chars_per_token: Estimated chars per token
            deduplicate: Whether to remove near-duplicate chunks
            include_metadata: Whether to include DOI/section in context
            db_path: Path to sme.db for APA reference lookup (optional)
        """
        self.max_context_tokens = max_context_tokens
        self.chars_per_token = chars_per_token
        self.max_chars = int(max_context_tokens * chars_per_token)
        self.deduplicate = deduplicate
        self.include_metadata = include_metadata
        
        # Initialize APA resolver if db_path provided
        if db_path:
            self.apa_resolver = APAReferenceResolver(db_path=db_path)
        else:
            # Try default path
            self.apa_resolver = APAReferenceResolver(db_path="data/sme.db")
    
    def build_context(
        self,
        results: List[RetrievalResult],
        max_per_doi: int = 2,  # Max chunks per paper
        min_unique_papers: int = 10,  # Min unique papers to include
        max_unique_papers: int = 150   # Max unique papers to include
    ) -> Tuple[str, List[RetrievalResult], List[str], Dict[str, int]]:
        """
        Build context string from retrieval results.
        
        Args:
            results: Retrieved and reranked results
            max_per_doi: Maximum chunks per paper (enforces diversity)
            min_unique_papers: Minimum number of unique papers
            max_unique_papers: Maximum number of unique papers
            
        Returns:
            Tuple of (context_string, used_results, apa_references, doi_to_number_map)
        """
        if not results:
            return "", [], [], {}
        
        # 12c: DOI-level deduplication for diversity
        results = self._limit_per_doi(results, max_per_doi)
        
        # Deduplicate if enabled
        if self.deduplicate:
            results = self._deduplicate(results)
        
        # Order by document and section for coherent reading
        results = self._order_by_document(results)
        
        # Build DOI -> paper number mapping (for consistent citation numbers)
        doi_to_number = {}
        paper_number = 0
        
        # First pass: collect all unique DOIs up to max_unique_papers
        unique_dois = []
        for result in results:
            doi = result.chunk.doi
            if doi and doi not in doi_to_number:
                paper_number += 1
                doi_to_number[doi] = paper_number
                unique_dois.append(doi)
                # Stop if we have enough unique papers
                if paper_number >= max_unique_papers:
                    break
        
        # Resolve DOIs to APA references — FIX (H6): Prioritize Qdrant payload
        # over DB lookup. The Qdrant payloads now contain pre-built APA references.
        apa_references = []
        doi_to_apa = {}  # P15 FIX: Persistent mapping — was only assigned in DB fallback branch
        for doi in unique_dois:
            apa_ref = ''
            # 1st: Check chunk metadata (from Qdrant payload — most authoritative)
            for result in results:
                if result.chunk.doi == doi:
                    apa_ref = result.chunk.metadata.get('apa_reference', '')
                    break
            # 2nd: Fallback to DB lookup
            if not apa_ref:
                db_resolved = self.apa_resolver.resolve([doi])
                apa_ref = db_resolved.get(doi, '')
            # 3rd: Last resort — use DOI URL
            if apa_ref:
                apa_references.append(apa_ref)
            else:
                apa_ref = f"https://doi.org/{doi}"
                apa_references.append(apa_ref)
            # P15 FIX: Always store in persistent mapping for downstream use
            doi_to_apa[doi] = apa_ref
        
        # Build context string with paper-level numbered citations
        context_parts = []
        used_results = []
        current_chars = 0
        
        for result in results:
            doi = result.chunk.doi
            # Skip if this paper isn't in our numbered set
            if doi not in doi_to_number:
                continue
                
            paper_num = doi_to_number[doi]
            
            # 12d: Apply text cleaning
            try:
                from src.utils.text_cleaner import clean_text
                cleaned_text = clean_text(result.chunk.text)
            except ImportError:
                cleaned_text = result.chunk.text
            
            # Format with PAPER number, not excerpt number
            chunk_text = self._format_chunk_numbered(result, paper_num, cleaned_text)
            chunk_chars = len(chunk_text)
            
            if current_chars + chunk_chars > self.max_chars:
                remaining = self.max_chars - current_chars
                if remaining > 200:
                    truncated = chunk_text[:remaining] + "..."
                    context_parts.append(truncated)
                    used_results.append(result)
                break
            
            context_parts.append(chunk_text)
            used_results.append(result)
            current_chars += chunk_chars
        
        context = "\n\n---\n\n".join(context_parts)
        
        # Log Context Utilization
        utilization = (current_chars / self.max_chars) * 100
        actually_used_paper_count = len(set(r.chunk.doi for r in used_results))
        logger.info(f"Context Utilization: {utilization:.1f}% ({current_chars}/{self.max_chars} chars)")
        logger.info(f"Context Construction: Included {len(context_parts)} chunks from {actually_used_paper_count} unique papers (DOIs numbered: {len(doi_to_number)}).")
        
        # FILTER: Only return citations/DOIs that were actually used in the text
        # This prevents "Aggregated 150 refs" vs "Used 20 sources" discrepancies
        actually_used_dois = set(r.chunk.doi for r in used_results)
        
        final_doi_to_number = {
            doi: num for doi, num in doi_to_number.items() 
            if doi in actually_used_dois
        }
        
        # Re-build APA references strictly from used papers
        # We need to preserve the order implied by paper numbers
        final_apa_references = []
        # Create a reverse map for sorting: number -> (doi, ref)
        # Note: We need original APA refs. We can rebuild them from used_results or filter the original list
        # Filtering original list is trickier because we didn't store DOI with it in the list.
        # Better: iterate through used_results to collect unique APA refs in order of appearance (or paper number)
        
        # Sort used DOIs by their assigned number
        sorted_used_dois = sorted(actually_used_dois, key=lambda d: final_doi_to_number[d])
        
        # Efficient lookup for APA ref from the pre-computed list? 
        # No, the pre-computed 'apa_references' list matches 'doi_to_number' insertion order.
        # But 'doi_to_number' contained extra papers.
        # Let's rebuild references from the used_results to be safe and accurate.
        
        seen_ref_dois = set()
        # Create a map of DOI -> APA Ref from all considered results (Loop 1) is not explicitly stored
        # But we can grab it from used_results
        
        # Wait, used_results contains multiple chunks per paper.
        # We need one ref per paper.
        doi_to_ref_map = {}
        for r in used_results:
            if r.chunk.doi not in doi_to_ref_map:
                ref = r.chunk.metadata.get('apa_reference', '')
                if ref:
                    doi_to_ref_map[r.chunk.doi] = ref
        
        for doi in sorted_used_dois:
            if doi in doi_to_apa:
                 final_apa_references.append(doi_to_apa[doi])
            elif doi in doi_to_ref_map:
                 final_apa_references.append(doi_to_ref_map[doi])
            else:
                 # Last resort fallback if not in map or metadata
                 final_apa_references.append(f"https://doi.org/{doi}")
        
        logger.debug(f"Built context with {len(used_results)} chunks from {len(final_doi_to_number)} papers (filtered from {len(doi_to_number)})")
        
        return context, used_results, final_apa_references, final_doi_to_number
    
    def _format_chunk_numbered(self, result: RetrievalResult, number: int, text: str) -> str:
        """Format a single chunk with numbered citation for context."""
        chunk = result.chunk
        
        # Get short citation from metadata
        citation = chunk.metadata.get('citation_str', f'[{chunk.doi}]')
        
        if self.include_metadata:
            header = f"[{number}] {citation}"
            if chunk.metadata.get('title'):
                header += f" - {chunk.metadata['title'][:80]}..."
            return f"{header}\n{text}"
        
        return f"[{number}] {text}"
    
    def _limit_per_doi(self, results: List[RetrievalResult], max_per_doi: int) -> List[RetrievalResult]:
        """Limit chunks per DOI to enforce source diversity (12c)."""
        doi_counts = {}
        diverse_results = []
        
        for r in results:
            doi = r.chunk.doi
            if doi_counts.get(doi, 0) < max_per_doi:
                diverse_results.append(r)
                doi_counts[doi] = doi_counts.get(doi, 0) + 1
        
        if len(diverse_results) < len(results):
            logger.debug(f"DOI diversity: kept {len(diverse_results)} from {len(results)}")
        
        return diverse_results

    def _format_chunk(self, result: RetrievalResult) -> str:
        """Format a single chunk for context (legacy, use _format_chunk_numbered)."""
        chunk = result.chunk
        
        if self.include_metadata:
            header = f"[Source: {chunk.doi}"
            if chunk.section:
                header += f" | Section: {chunk.section}"
            header += "]"
            return f"{header}\n{chunk.text}"
        
        return chunk.text
    
    def _deduplicate(
        self,
        results: List[RetrievalResult],
        similarity_threshold: float = 0.8
    ) -> List[RetrievalResult]:
        """Remove near-duplicate chunks."""
        if len(results) <= 1:
            return results
        
        deduplicated = [results[0]]
        
        for result in results[1:]:
            is_duplicate = False
            
            for existing in deduplicated:
                similarity = self._text_similarity(
                    result.chunk.text,
                    existing.chunk.text
                )
                if similarity > similarity_threshold:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                deduplicated.append(result)
        
        if len(deduplicated) < len(results):
            logger.debug(f"Removed {len(results) - len(deduplicated)} duplicate chunks")
        
        return deduplicated
    
    def _text_similarity(self, text1: str, text2: str) -> float:
        """Calculate simple Jaccard similarity between texts."""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        
        return intersection / union
    
    def _order_by_document(
        self,
        results: List[RetrievalResult]
    ) -> List[RetrievalResult]:
        """
        Order results by document and section for coherent reading.
        
        Keeps overall relevance order but groups chunks from same doc.
        """
        # Group by DOI
        by_doi: Dict[str, List[RetrievalResult]] = {}
        doi_order = []  # Preserve first-seen order
        
        for result in results:
            doi = result.chunk.doi
            if doi not in by_doi:
                by_doi[doi] = []
                doi_order.append(doi)
            by_doi[doi].append(result)
        
        # Sort chunks within each doc by chunk index
        for doi in by_doi:
            by_doi[doi].sort(key=lambda r: r.chunk.chunk_index)
        
        # Reconstruct list maintaining doc order but grouping by doc
        ordered = []
        for doi in doi_order:
            ordered.extend(by_doi[doi])
        
        return ordered
    
    def get_source_dois(self, results: List[RetrievalResult]) -> List[str]:
        """Get unique DOIs from results."""
        seen = set()
        dois = []
        for result in results:
            doi = result.chunk.doi
            if doi not in seen:
                seen.add(doi)
                dois.append(doi)
        return dois


def create_context_builder(
    max_context_tokens: int = 6000,
    deduplicate: bool = True,
    db_path: Optional[str] = None
) -> ContextBuilder:
    """
    Factory function to create a context builder.
    
    Args:
        max_context_tokens: Maximum tokens in context
        deduplicate: Whether to remove near-duplicate chunks
        db_path: Path to sme.db for APA reference lookup
    """
    return ContextBuilder(
        max_context_tokens=max_context_tokens,
        deduplicate=deduplicate,
        db_path=db_path
    )
