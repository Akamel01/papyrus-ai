"""
Dynamic Citation Density Calculator for SME RAG System.

Calculates the required number of unique citations based on:
1. Question complexity (simple/moderate/complex)
2. Expected response length
3. User-selected density level (Low/Medium/High)

Benchmarks for HIGH density:
- Complex question + long answer: 30+ unique citations
- Moderate question + moderate answer: 20-30 unique citations  
- Simple question: 10-20 unique citations

Medium = 70% of high density
Low = 30% of high density
"""

import re
import logging
from typing import Tuple, Dict

logger = logging.getLogger(__name__)


# Complexity detection keywords and patterns
COMPLEX_INDICATORS = [
    # Academic/research terms
    r'\b(comprehensive|systematic|integrated|meta-analysis|literature review)\b',
    r'\b(compare|comparison|contrast|synthesize|analyze|evaluate)\b',
    r'\b(methodology|methodological|framework|theoretical)\b',
    r'\b(variables|factors|moderators|mediators|mechanisms)\b',
    r'\b(network|spatial|temporal|multi|heterogeneity)\b',
    # Multiple topics/aspects
    r'\b(and|also|additionally|furthermore|moreover)\b.*\b(and|also)\b',
    # Technical depth markers
    r'\b(effectiveness|efficacy|impact|outcome|treatment effect)\b',
    r'\b(crash modification|CMF|CRF|reduction factor)\b',
    r'\b(halo effect|spillover|radial|upstream|downstream)\b',
]

MODERATE_INDICATORS = [
    r'\b(explain|describe|discuss|outline|summarize)\b',
    r'\b(how|why|what factors|what variables)\b',
    r'\b(relationship|correlation|association|influence)\b',
    r'\b(examples|instances|cases|scenarios)\b',
]

SIMPLE_INDICATORS = [
    r'\b(what is|define|definition|meaning)\b',
    r'\b(when|where|who)\b',
    r'\b(list|name|identify)\b',
    r'\b(simple|basic|brief|quick)\b',
]


def assess_question_complexity(query: str) -> str:
    """
    Assess the complexity of a question.
    
    Args:
        query: The user's question
        
    Returns:
        "complex", "moderate", or "simple"
        
    Raises:
        ValueError: If query is None or empty (indicates caller bug)
    """
    # Fail loudly if query is None - this indicates a caller bug
    if not query:
        raise ValueError(f"assess_question_complexity received invalid query: {query!r}. This is a caller bug - the query must be provided.")
    
    query_lower = query.lower()
    query_len = len(query.split())
    
    # Score the query
    complex_score = 0
    moderate_score = 0
    simple_score = 0
    
    for pattern in COMPLEX_INDICATORS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            complex_score += 1
    
    for pattern in MODERATE_INDICATORS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            moderate_score += 1
    
    for pattern in SIMPLE_INDICATORS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            simple_score += 1
    
    # Length bonus for complexity
    if query_len > 40:
        complex_score += 2
    elif query_len > 20:
        moderate_score += 1
    
    # Multiple sentences indicate more complex request
    sentence_count = len(re.findall(r'[.!?]', query))
    if sentence_count >= 3:
        complex_score += 2
    elif sentence_count >= 2:
        moderate_score += 1
    
    # Academic writing indicators
    if any(term in query_lower for term in ['academic', 'scholarly', 'research', 'literature']):
        complex_score += 2
    
    # Determine complexity
    if complex_score >= 3 or (complex_score >= 2 and query_len > 30):
        return "complex"
    elif moderate_score >= 2 or complex_score >= 1:
        return "moderate"
    else:
        return "simple"


def estimate_response_length(query: str, depth: str) -> str:
    """
    Estimate expected response length based on query and depth.
    
    Args:
        query: The user's question
        depth: Research depth setting ("Low", "Medium", "High")
        
    Returns:
        "long", "moderate", or "short"
    """
    complexity = assess_question_complexity(query)
    
    # Depth influences response length
    depth_multiplier = {"Low": 0.5, "Medium": 1.0, "High": 1.5}.get(depth, 1.0)
    
    # Base length from complexity
    if complexity == "complex":
        base = "long"
    elif complexity == "moderate":
        base = "moderate" 
    else:
        base = "short"
    
    # Adjust based on depth
    if depth == "High" and base != "long":
        return "moderate" if base == "short" else "long"
    elif depth == "Low" and base != "short":
        return "moderate" if base == "long" else "short"
    
    return base


def calculate_citation_target(
    query: str,
    depth: str = "Medium",
    density_level: str = "Medium",
    auto_decide: bool = True
) -> Dict[str, any]:
    """
    Calculate the target number of unique citations.
    
    Args:
        query: The user's question
        depth: Research depth setting
        density_level: User-selected density ("Low", "Medium", "High")
        auto_decide: If True, AI determines density automatically
        
    Returns:
        Dict with citation targets and complexity info
    """
    complexity = assess_question_complexity(query)
    response_length = estimate_response_length(query, depth)
    
    # Define HIGH density baselines (benchmark values)
    high_density_targets = {
        ("complex", "long"): 30,
        ("complex", "moderate"): 25,
        ("complex", "short"): 20,
        ("moderate", "long"): 25,
        ("moderate", "moderate"): 20,
        ("moderate", "short"): 15,
        ("simple", "long"): 20,
        ("simple", "moderate"): 15,
        ("simple", "short"): 10,
    }
    
    # Get high density target
    high_target = high_density_targets.get((complexity, response_length), 20)
    
    if auto_decide:
        # AI decides: use complexity-appropriate level
        if complexity == "complex":
            target = high_target  # Use full high density
        elif complexity == "moderate":
            target = int(high_target * 0.85)  # 85% of high
        else:
            target = int(high_target * 0.70)  # 70% of high for simple
        effective_density = "auto"
    else:
        # User-specified density
        if density_level == "High":
            target = high_target
        elif density_level == "Medium":
            target = max(5, int(high_target * 0.70))  # 70% of high
        else:  # Low
            target = max(3, int(high_target * 0.30))  # 30% of high
        effective_density = density_level
    
    # Ensure minimum reasonable targets
    target = max(3, target)
    
    result = {
        "target_citations": target,
        "min_citations": max(3, int(target * 0.7)),
        "max_citations": int(target * 1.3),
        "complexity": complexity,
        "response_length": response_length,
        "density_level": effective_density,
        "high_baseline": high_target
    }
    
    logger.info(f"Citation target: {target} (complexity={complexity}, length={response_length}, density={effective_density})")
    
    return result


def generate_citation_instructions(citation_info: Dict) -> str:
    """
    Generate prompt instructions based on citation targets.
    
    Args:
        citation_info: Output from calculate_citation_target
        
    Returns:
        Instruction string to append to prompt
    """
    target = citation_info["target_citations"]
    min_cit = citation_info["min_citations"]
    complexity = citation_info["complexity"]
    
    # Density descriptions
    density_desc = {
        "complex": "This is a complex, comprehensive question requiring extensive citation support.",
        "moderate": "This is a moderately complex question requiring solid citation coverage.",
        "simple": "This is a focused question requiring key citations for main claims."
    }
    
    instructions = f"""

CITATION REQUIREMENTS (MANDATORY):
{density_desc.get(complexity, "")}

- You MUST cite at LEAST {min_cit} unique sources
- Target citation count: {target} unique sources
- Each unique citation should be from a different paper (unique DOI)
- Citations should use APA in-text format: (Author, Year) parenthetical or Author (Year) narrative
- Both forms are correct — choose based on sentence structure
- Every factual claim, statistic, and finding MUST have a citation
- For complex topics, cite multiple supporting sources for key claims
- Do NOT repeat the same citation excessively - aim for diversity

CITATION QUALITY STANDARDS:
- Primary claims: cite 2-3 supporting sources
- Statistics and specific findings: always cite the original source
- Methodological details: cite the relevant methodology papers
- Comparative statements: cite sources for both/all sides being compared
"""
    
    return instructions


# Convenience function
def get_citation_instructions(
    query: str,
    depth: str = "Medium", 
    density_level: str = "Medium",
    auto_decide: bool = True
) -> str:
    """
    Get citation instructions for a query.
    
    Args:
        query: User's question
        depth: Research depth
        density_level: User-selected density
        auto_decide: Whether AI decides density
        
    Returns:
        Instruction string for the LLM prompt
    """
    citation_info = calculate_citation_target(
        query=query,
        depth=depth,
        density_level=density_level,
        auto_decide=auto_decide
    )
    return generate_citation_instructions(citation_info)
