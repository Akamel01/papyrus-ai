"""
Question Classifier for Dynamic Paper Selection.

Classifies research questions by complexity to determine optimal paper count.
"""

import re
from typing import Dict, Tuple
from dataclasses import dataclass


@dataclass
class QuestionClassification:
    """Classification result for a research question."""
    question_type: str  # definition, comparison, mechanism, review, general
    complexity: str     # simple, moderate, complex
    min_papers: int
    max_papers: int
    description: str


# Question type patterns
REVIEW_PATTERNS = [
    r'\b(systematic\s+review|meta[\-\s]?analysis|scoping\s+review)\b',
    r'\b(comprehensive\s+review|literature\s+review|narrative\s+review)\b',
    r'\b(quantitative\s+review|qualitative\s+review|mixed[\-\s]?methods?\s+review)\b',
    r'\b(state[\-\s]?of[\-\s]?the[\-\s]?art|overview\s+of|survey\s+of)\b',
    r'\b(all\s+(?:studies|research|papers|evidence)\s+on)\b',
]

COMPARISON_PATTERNS = [
    r'\b(compare|comparison|versus|vs\.?|differ(?:ence)?s?\s+between)\b',
    r'\b(which\s+is\s+better|pros\s+and\s+cons|advantages?\s+and\s+disadvantages?)\b',
    r'\b(similarities?\s+and\s+differences?|relative\s+to)\b',
]

MECHANISM_PATTERNS = [
    r'\b(how\s+does|mechanism|why\s+does|what\s+causes?)\b',
    r'\b(relationship\s+between|effect\s+of|impact\s+of|influence\s+of)\b',
    r'\b(factors?\s+(?:that\s+)?affect|determinants?\s+of)\b',
]

DEFINITION_PATTERNS = [
    r'\b(what\s+is|define|definition\s+of|meaning\s+of)\b',
    r'\b(explain\s+(?:the\s+)?(?:term|concept|notion))\b',
    r'^\s*what\s+(?:is|are)\s+\w+\s*\??\s*$',  # Simple "What is X?" queries
]


def classify_question(query: str, depth: str = "Medium") -> QuestionClassification:
    """
    Classify a research question and suggest paper range.
    
    Args:
        query: User's research question
        depth: Current depth setting (Low/Medium/High)
        
    Returns:
        QuestionClassification with type, complexity, and paper range
    """
    query_lower = query.lower().strip()
    word_count = len(query.split())
    
    # Check for review-type questions (most papers needed)
    for pattern in REVIEW_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            return QuestionClassification(
                question_type="review",
                complexity="complex",
                min_papers=20,
                max_papers=50,
                description="Review/synthesis question - requires comprehensive source coverage"
            )
    
    # Check for comparison questions
    for pattern in COMPARISON_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            return QuestionClassification(
                question_type="comparison",
                complexity="moderate",
                min_papers=8,
                max_papers=20,
                description="Comparison question - needs multiple perspectives"
            )
    
    # Check for mechanism/relationship questions
    for pattern in MECHANISM_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            return QuestionClassification(
                question_type="mechanism",
                complexity="moderate",
                min_papers=10,
                max_papers=25,
                description="Mechanism/relationship question - needs causal evidence"
            )
    
    # Check for simple definition questions
    for pattern in DEFINITION_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            # Very short definition queries need fewer papers
            if word_count <= 6:
                return QuestionClassification(
                    question_type="definition",
                    complexity="simple",
                    min_papers=3,
                    max_papers=8,
                    description="Definition question - focused answer needed"
                )
    
    # Default: general question, adjust by depth
    depth_ranges = {
        "Low": (3, 8),
        "Medium": (8, 15),
        "High": (15, 30)
    }
    min_p, max_p = depth_ranges.get(depth, (8, 15))
    
    # Adjust by query length/complexity
    if word_count > 20:
        min_p = min(min_p + 5, 25)
        max_p = min(max_p + 10, 50)
    
    return QuestionClassification(
        question_type="general",
        complexity="moderate" if word_count > 10 else "simple",
        min_papers=min_p,
        max_papers=max_p,
        description="General research question"
    )


def get_paper_range(query: str, depth: str = "Medium", 
                    auto_decide: bool = True,
                    manual_range: Tuple[int, int] = None) -> Tuple[int, int]:
    """
    Get the paper range to use for a query.
    
    Args:
        query: User's question
        depth: Depth setting
        auto_decide: Whether to use AI classification
        manual_range: User-specified range (min, max)
        
    Returns:
        Tuple of (min_papers, max_papers)
    """
    if not auto_decide and manual_range:
        return manual_range
    
    classification = classify_question(query, depth)
    return (classification.min_papers, classification.max_papers)


def get_classification_info(query: str, depth: str = "Medium") -> str:
    """
    Get human-readable classification info for display.
    """
    c = classify_question(query, depth)
    return f"📊 {c.question_type.title()} ({c.complexity}) → {c.min_papers}-{c.max_papers} papers"
