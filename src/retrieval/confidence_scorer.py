"""
Confidence Scorer for Sequential RAG.

Calculates confidence from initial search results to determine if reflection is needed.
"""

from dataclasses import dataclass
from typing import List, Dict, Set
import re


@dataclass
class ConfidenceScore:
    """Confidence assessment for search results."""
    score: float           # 0.0 - 1.0
    signals: Dict[str, float]
    recommendation: str    # "generate", "expand", "full_sequential"


def calculate_confidence(results: List, query: str, target_papers: int = 10) -> ConfidenceScore:
    """
    Calculate confidence based on multiple signals.
    
    Args:
        results: List of RetrievalResult objects
        query: Original user query
        target_papers: Target number of unique papers
        
    Returns:
        ConfidenceScore with score, signals, and recommendation
    """
    if not results:
        return ConfidenceScore(
            score=0.0,
            signals={},
            recommendation="full_sequential"
        )
    
    signals = {}
    
    # Signal 1: Relevance coverage (% of results with high score)
    high_relevance_threshold = 0.75
    high_relevance_count = sum(1 for r in results if getattr(r, 'score', 0) > high_relevance_threshold)
    signals["relevance_coverage"] = min(1.0, high_relevance_count / max(len(results), 1))
    
    # Signal 2: DOI diversity (unique papers found vs target)
    unique_dois = set()
    for r in results:
        doi = getattr(r.chunk, 'doi', None) if hasattr(r, 'chunk') else None
        if doi:
            unique_dois.add(doi)
    signals["doi_diversity"] = min(1.0, len(unique_dois) / target_papers)
    
    # Signal 3: Term coverage (query terms found in results)
    query_terms = _extract_key_terms(query)
    if query_terms:
        terms_found = 0
        result_text = " ".join(
            r.chunk.text.lower() if hasattr(r, 'chunk') else ""
            for r in results[:20]  # Check first 20 results
        )
        for term in query_terms:
            if term.lower() in result_text:
                terms_found += 1
        signals["term_coverage"] = terms_found / len(query_terms)
    else:
        signals["term_coverage"] = 0.5  # Neutral if no terms
    
    # Signal 4: Section diversity (intro, methods, results, discussion)
    sections_found = set()
    for r in results[:20]:
        if hasattr(r, 'chunk') and hasattr(r.chunk, 'metadata'):
            section = r.chunk.metadata.get('section_type', '').lower()
            if section:
                sections_found.add(section)
    signals["section_diversity"] = min(1.0, len(sections_found) / 4)  # 4 main sections
    
    # Calculate weighted overall score
    weights = {
        "relevance_coverage": 0.35,
        "doi_diversity": 0.30,
        "term_coverage": 0.25,
        "section_diversity": 0.10
    }
    
    overall_score = sum(
        signals.get(key, 0) * weight
        for key, weight in weights.items()
    )
    
    # Determine recommendation
    if overall_score >= 0.85:
        recommendation = "generate"  # Skip reflection
    elif overall_score >= 0.65:
        recommendation = "expand"    # Quick keyword expansion
    else:
        recommendation = "full_sequential"  # Full reflection
    
    return ConfidenceScore(
        score=overall_score,
        signals=signals,
        recommendation=recommendation
    )


def _extract_key_terms(query: str) -> List[str]:
    """Extract key terms from query for term coverage calculation."""
    # Remove common stop words
    stop_words = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
        'what', 'how', 'why', 'when', 'where', 'which', 'who',
        'do', 'does', 'did', 'can', 'could', 'would', 'should',
        'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of',
        'with', 'by', 'from', 'as', 'about', 'between'
    }
    
    # Extract words
    words = re.findall(r'\b[a-zA-Z]{3,}\b', query.lower())
    
    # Filter stop words and return
    return [w for w in words if w not in stop_words]


def should_skip_reflection(confidence: ConfidenceScore) -> bool:
    """Check if we can skip reflection based on confidence."""
    return confidence.recommendation == "generate"


def get_confidence_emoji(score: float) -> str:
    """Get emoji indicator for confidence level."""
    if score >= 0.80:  # Lowered from 0.85
        return "🟢"
    elif score >= 0.65:
        return "🟡"
    else:
        return "🔴"
