"""
Entity Extractor for Sequential RAG.

Extracts domain-specific entities from context to generate targeted follow-up queries.
"""

import re
from dataclasses import dataclass, field
from typing import List, Set


@dataclass
class ExtractedEntities:
    """Domain-specific entities extracted from context."""
    methodologies: List[str] = field(default_factory=list)
    contexts: List[str] = field(default_factory=list)
    outcomes: List[str] = field(default_factory=list)
    interventions: List[str] = field(default_factory=list)
    metrics: List[str] = field(default_factory=list)


# Domain-specific patterns for transportation safety research
METHODOLOGY_PATTERNS = [
    r'\b(empirical\s+bayes|EB)\b',
    r'\b(before[\-\s]?after\s+stud(?:y|ies))\b',
    r'\b(RCT|randomized\s+controlled?\s+trial)\b',
    r'\b(cross[\-\s]?sectional)\b',
    r'\b(longitudinal\s+stud(?:y|ies))\b',
    r'\b(meta[\-\s]?analysis)\b',
    r'\b(case[\-\s]?control)\b',
    r'\b(propensity\s+score)\b',
    r'\b(regression\s+to\s+(?:the\s+)?mean)\b',
    r'\b(crash\s+modification\s+factor|CMF)\b',
    r'\b(safety\s+performance\s+function|SPF)\b',
]

CONTEXT_PATTERNS = [
    r'\b(urban|rural|suburban)\b',
    r'\b(intersection|signalized|unsignalized)\b',
    r'\b(highway|arterial|freeway|expressway)\b',
    r'\b(school\s+zone|work\s+zone)\b',
    r'\b(residential|commercial|industrial)\b',
    r'\b(high[\-\s]?speed|low[\-\s]?speed)\b',
    r'\b(daytime|nighttime|dark\s+conditions?)\b',
    r'\b(wet|dry|adverse\s+weather)\b',
]

OUTCOME_PATTERNS = [
    r'\b(crash\s+reduction|crash\s+frequency)\b',
    r'\b(crash\s+severity|fatal(?:ity|ities)?)\b',
    r'\b(injur(?:y|ies)|serious\s+injur(?:y|ies))\b',
    r'\b(speed\s+compliance|speed\s+reduction)\b',
    r'\b(red[\-\s]?light\s+violation)\b',
    r'\b(rear[\-\s]?end\s+crash(?:es)?)\b',
    r'\b(angle\s+crash(?:es)?|right[\-\s]?angle)\b',
    r'\b(pedestrian|cyclist|vulnerable\s+road\s+user)\b',
]

INTERVENTION_PATTERNS = [
    r'\b(red[\-\s]?light\s+camera|RLC)\b',
    r'\b(speed\s+camera|photo\s+enforcement)\b',
    r'\b(automated\s+enforcement)\b',
    r'\b(traffic\s+signal|signal\s+timing)\b',
    r'\b(speed\s+limit|posted\s+speed)\b',
    r'\b(warning\s+sign|advance\s+warning)\b',
    r'\b(geometric\s+improvement)\b',
]

METRIC_PATTERNS = [
    r'\b(TTC|time[\-\s]?to[\-\s]?collision)\b',
    r'\b(PET|post[\-\s]?encroachment[\-\s]?time)\b',
    r'\b(DRAC|deceleration\s+rate)\b',
    r'\b(85th\s+percentile)\b',
    r'\b(odds\s+ratio|OR)\b',
    r'\b(relative\s+risk|RR)\b',
    r'\b(confidence\s+interval|CI)\b',
    r'\b(p[\-\s]?value|significance)\b',
]


def extract_entities(context: str) -> ExtractedEntities:
    """
    Extract domain-specific entities from context.
    
    Args:
        context: Text to extract entities from
        
    Returns:
        ExtractedEntities with categorized findings
    """
    entities = ExtractedEntities()
    
    # Extract each category
    entities.methodologies = _extract_unique_matches(context, METHODOLOGY_PATTERNS)
    entities.contexts = _extract_unique_matches(context, CONTEXT_PATTERNS)
    entities.outcomes = _extract_unique_matches(context, OUTCOME_PATTERNS)
    entities.interventions = _extract_unique_matches(context, INTERVENTION_PATTERNS)
    entities.metrics = _extract_unique_matches(context, METRIC_PATTERNS)
    
    return entities


def _extract_unique_matches(text: str, patterns: List[str]) -> List[str]:
    """Extract unique matches for a list of patterns."""
    matches: Set[str] = set()
    
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            # Normalize the match
            matched_text = match.group(0).lower().strip()
            matches.add(matched_text)
    
    return sorted(list(matches))


def generate_targeted_queries(
    original_query: str,
    entities: ExtractedEntities,
    gaps: List = None
) -> List[str]:
    """
    Generate targeted follow-up queries from entities and gaps.
    
    Args:
        original_query: Original user question
        entities: Extracted entities from current context
        gaps: Gap objects from gap_analyzer (optional)
        
    Returns:
        List of targeted follow-up queries
    """
    queries = []
    
    # If we have gaps, use their suggested queries first
    if gaps:
        for gap in gaps[:2]:
            if hasattr(gap, 'suggested_query') and gap.suggested_query:
                queries.append(gap.suggested_query)
    
    # Generate queries for contexts not well covered
    # (This would ideally compare against what's already found)
    
    # If original query mentions camera/enforcement, look for specific outcomes
    if 'camera' in original_query.lower() or 'enforcement' in original_query.lower():
        if 'rear-end crash' not in str(entities.outcomes):
            queries.append("red-light camera rear-end crash effects spillover")
        if 'speed compliance' not in str(entities.outcomes):
            queries.append("speed camera compliance rate effectiveness")
    
    # If asking about effectiveness, ensure methodology coverage
    if 'effective' in original_query.lower() or 'effectiveness' in original_query.lower():
        if 'empirical bayes' not in str(entities.methodologies):
            queries.append("crash modification factor empirical bayes methodology")
    
    # Limit and deduplicate
    unique_queries = []
    seen = set()
    for q in queries:
        q_lower = q.lower()
        if q_lower not in seen:
            seen.add(q_lower)
            unique_queries.append(q)
    
    return unique_queries[:3]  # Max 3 follow-ups


def entities_to_display_string(entities: ExtractedEntities) -> str:
    """Format entities for display."""
    lines = []
    
    if entities.methodologies:
        lines.append(f"📊 Methods: {', '.join(entities.methodologies[:5])}")
    if entities.contexts:
        lines.append(f"📍 Contexts: {', '.join(entities.contexts[:5])}")
    if entities.outcomes:
        lines.append(f"📈 Outcomes: {', '.join(entities.outcomes[:5])}")
    if entities.interventions:
        lines.append(f"🚦 Interventions: {', '.join(entities.interventions[:5])}")
    
    return "\n".join(lines) if lines else "No domain entities extracted"


def get_coverage_score(entities: ExtractedEntities) -> float:
    """Calculate coverage score based on entity diversity."""
    total_categories = 5
    filled = 0
    
    if entities.methodologies:
        filled += 1
    if entities.contexts:
        filled += 1
    if entities.outcomes:
        filled += 1
    if entities.interventions:
        filled += 1
    if entities.metrics:
        filled += 1
    
    return filled / total_categories
