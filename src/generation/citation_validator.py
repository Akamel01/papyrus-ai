"""
Citation Validator for SME RAG System (Phase 12b.3).

Post-processes LLM responses to validate citation compliance:
1. Checks that responses use numbered citations [1], [2], etc.
2. Validates that citation numbers match available sources
3. Measures citation density (citations per paragraph)
4. Flags uncited claims

Usage:
    validator = CitationValidator(num_sources=5)
    result = validator.validate(response_text)
    if result['compliance_score'] < 0.7:
        # Consider regenerating or flagging response
"""

import re
import logging
from typing import List, Dict, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of citation validation."""
    compliance_score: float  # 0.0 to 1.0
    cited_sources: List[int]  # Which source numbers were cited
    uncited_paragraphs: List[int]  # Paragraph indices without citations
    invalid_citations: List[str]  # Citations to non-existent sources
    total_paragraphs: int
    total_citations: int
    issues: List[str]  # Human-readable issues


class CitationValidator:
    """
    Validates LLM responses for citation compliance.
    """
    
    def __init__(self, num_sources: int, author_names: List[str] = None):
        """
        Initialize validator.
        
        Args:
            num_sources: Number of sources provided in context (for validation)
            author_names: Optional list of author surnames to detect (Author, Year) citations
        """
        self.num_sources = num_sources
        self.author_names = author_names or []
        # Pattern to match numbered citations like [1], [2, 3], [1-3]
        self.numbered_pattern = re.compile(r'\[(\d+(?:[-,\s]\d+)*)\]')
        # Pattern to match (Author, Year) or (Author et al., Year) citations
        # Expanded to match: (Smith et al. 2024), (A & B, 2020), (Author-Name, 2019)
        self.author_year_pattern = re.compile(
            r'\(([A-Z][a-zA-Zé\-\']+(?:\s*(?:et\s+al\.?|,?\s*&?\s*[A-Z][a-zA-Z\-]+)+)?),?\s*(\d{4})\)'
        )
        # C6 FIX: Pattern for NARRATIVE form: Author (Year), Author et al. (Year)
        self.narrative_citation_pattern = re.compile(
            r"[A-Z][a-zA-Z\-\']+(?:\s+(?:and|&)\s+[A-Z][a-zA-Z\-\']+)?(?:\s+et\s+al\.?)?\s*\(\d{4}\)"
        )
        # For backwards compatibility
        self.citation_pattern = self.numbered_pattern
    
    def validate(self, response: str) -> ValidationResult:
        """
        Validate a response for citation compliance.
        
        Args:
            response: The LLM-generated response text
            
        Returns:
            ValidationResult with compliance metrics
        """
        paragraphs = self._split_paragraphs(response)
        
        cited_sources = set()
        author_year_citations = 0  # Track (Author, Year) citations separately
        uncited_paragraphs = []
        invalid_citations = []
        total_citations = 0
        issues = []
        
        for i, para in enumerate(paragraphs):
            # Find all citations in this paragraph
            citations_in_para = self._extract_citations(para)
            
            if not citations_in_para:
                # Check if paragraph contains factual claims
                if self._contains_factual_claim(para):
                    uncited_paragraphs.append(i)
            else:
                total_citations += len(citations_in_para)
                for cite in citations_in_para:
                    # -1 indicates (Author, Year) citation - valid and counts toward compliance
                    if cite == -1:
                        author_year_citations += 1
                    elif 1 <= cite <= self.num_sources:
                        cited_sources.add(cite)
                    else:
                        invalid_citations.append(f"[{cite}]")
        
        # Calculate compliance score
        total_paragraphs = len(paragraphs)
        factual_paragraphs = sum(1 for p in paragraphs if self._contains_factual_claim(p))
        
        if factual_paragraphs == 0:
            compliance_score = 1.0
        else:
            cited_factual = factual_paragraphs - len(uncited_paragraphs)
            compliance_score = cited_factual / factual_paragraphs
        
        # Bonus for high citation count (rewards heavily-cited responses)
        if total_citations >= 15:
            compliance_score = min(1.0, compliance_score + 0.10)
        if total_citations >= 25:
            compliance_score = min(1.0, compliance_score + 0.10)
        
        # Penalize for invalid citations (but not for author-year format)
        if invalid_citations:
            compliance_score *= 0.8
            issues.append(f"Invalid citations to non-existent sources: {invalid_citations}")
        
        # Check source diversity - include author-year citations in coverage
        total_unique_citations = len(cited_sources) + min(author_year_citations, self.num_sources - len(cited_sources))
        source_coverage = total_unique_citations / self.num_sources if self.num_sources > 0 else 0
        
        # Only flag low coverage if both numbered AND author-year citations are low
        if source_coverage < 0.3 and author_year_citations < 3:
            issues.append(f"Low source coverage: only used {len(cited_sources)} numbered + {author_year_citations} author-year citations")
        
        # Build issues list
        if uncited_paragraphs:
            issues.append(f"Paragraphs without citations: {uncited_paragraphs}")
        
        return ValidationResult(
            compliance_score=compliance_score,
            cited_sources=sorted(cited_sources),
            uncited_paragraphs=uncited_paragraphs,
            invalid_citations=invalid_citations,
            total_paragraphs=total_paragraphs,
            total_citations=total_citations,
            issues=issues
        )
    
    def _split_paragraphs(self, text: str) -> List[str]:
        """Split text into paragraphs."""
        # Split on double newlines or markdown headers
        paragraphs = re.split(r'\n\n+|\n(?=#+\s)', text)
        # Filter out empty paragraphs and very short lines
        return [p.strip() for p in paragraphs if len(p.strip()) > 20]
    
    def _extract_citations(self, text: str) -> List[int]:
        """Extract all citation indicators from text.
        
        Detects both:
        - Numbered citations: [1], [2, 3], [1-3]
        - Author-year citations: (Author, Year), (Author et al., Year)
        
        For (Author, Year) citations, we assign placeholder numbers since we 
        can't map them to specific source indices without the author list.
        """
        citations = []
        
        # Extract numbered citations
        numbered_matches = self.numbered_pattern.findall(text)
        for match in numbered_matches:
            # Handle ranges like [1-3] and lists like [1, 2]
            if '-' in match:
                parts = match.split('-')
                try:
                    start, end = int(parts[0].strip()), int(parts[1].strip())
                    citations.extend(range(start, end + 1))
                except ValueError:
                    pass
            else:
                nums = re.findall(r'\d+', match)
                citations.extend(int(n) for n in nums)
        
        # Extract PARENTHETICAL (Author, Year) citations
        # Each one counts as 1 citation (we use placeholder -1 since we can't map to source number)
        author_year_matches = self.author_year_pattern.findall(text)
        for author, year in author_year_matches:
            citations.append(-1)
        
        # C6 FIX: Extract NARRATIVE Author (Year) citations
        narrative_matches = self.narrative_citation_pattern.findall(text)
        for match in narrative_matches:
            citations.append(-1)
        
        return citations
    
    def _has_any_citation(self, text: str) -> bool:
        """Check if text has any citation (numbered, parenthetical, or narrative)."""
        has_numbered = bool(self.numbered_pattern.search(text))
        has_author_year = bool(self.author_year_pattern.search(text))
        has_narrative = bool(self.narrative_citation_pattern.search(text))
        return has_numbered or has_author_year or has_narrative
    
    def _contains_factual_claim(self, paragraph: str) -> bool:
        """
        Heuristically detect if a paragraph contains factual claims that need citation.
        """
        # Skip headers, questions, and meta-text
        if paragraph.startswith('#') or paragraph.startswith('**'):
            return False
        if paragraph.strip().endswith('?'):
            return False
        if 'References' in paragraph or 'limitations' in paragraph.lower():
            return False
        
        # Skip short paragraphs (unlikely to need citations)
        if len(paragraph) < 100:
            return False
        
        # Skip introductory and summary paragraphs
        para_lower = paragraph.lower().strip()
        intro_phrases = ('in this', 'this section', 'overall', 'in summary', 
                        'to summarize', 'in conclusion', 'the following')
        if any(para_lower.startswith(phrase) for phrase in intro_phrases):
            return False
        
        # Patterns that indicate factual claims
        factual_patterns = [
            r'\b(found|demonstrated|showed|reported|indicates?|suggests?)\b',
            r'\b(increas|decreas|reduc|improv)e[ds]?\b',
            r'\b\d+%\b',  # Percentages
            r'\b(p\s*[<>=]\s*0?\.\d+)\b',  # P-values
            r'\bp<0\.05\b',
            r'\b(OR|RR|CI)\s*[:=]',  # Statistical measures
            r'\b(significant|correlation|effect)\b',
        ]
        
        for pattern in factual_patterns:
            if re.search(pattern, paragraph, re.IGNORECASE):
                return True
        
        # Check for declarative statements (has verbs and nouns)
        words = paragraph.lower().split()
        has_verb = any(w.endswith(('ed', 'es', 'ing', 'tion')) for w in words)
        
        return has_verb and len(words) > 10


def validate_response(response: str, num_sources: int) -> ValidationResult:
    """
    Convenience function to validate a response.
    
    Args:
        response: LLM response text
        num_sources: Number of sources in context
        
    Returns:
        ValidationResult
    """
    validator = CitationValidator(num_sources=num_sources)
    return validator.validate(response)


def get_compliance_badge(score: float) -> str:
    """
    Get a visual badge for compliance score.
    
    Returns emoji badge based on score.
    """
    if score >= 0.9:
        return "🟢 Excellent"
    elif score >= 0.7:
        return "🟡 Good"
    elif score >= 0.5:
        return "🟠 Fair"
    else:
        return "🔴 Poor"
