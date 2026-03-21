"""
Gap Analyzer for Sequential RAG.

Identifies specific knowledge gaps in initial search results using structured output.
"""

import json
import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Gap:
    """A specific knowledge gap identified in the results."""
    gap_type: str        # "methodology", "context", "outcome", "timeframe", "geography"
    description: str     # What's missing
    suggested_query: str # Follow-up query to fill the gap
    priority: float      # 0.0 - 1.0


@dataclass
class GapAnalysis:
    """Complete gap analysis result."""
    has_sufficient_evidence: bool
    confidence_if_answered_now: float
    gaps: List[Gap]
    

GAP_ANALYSIS_PROMPT = """Analyze the search results for gaps in evidence needed to answer this question.

QUESTION: {query}

AVAILABLE CONTEXT (summary):
{context_summary}

Respond with ONLY valid JSON in this exact format:
{{
    "has_sufficient_evidence": true/false,
    "confidence_if_answered_now": 0.0-1.0,
    "gaps": [
        {{
            "gap_type": "methodology|context|outcome|timeframe|geography",
            "description": "What specific information is missing",
            "suggested_query": "Search query to find this information",
            "priority": 0.0-1.0
        }}
    ]
}}

Gap types:
- methodology: Missing study designs (RCT, before-after, etc.)
- context: Missing specific contexts (urban, rural, highway, school zone)
- outcome: Missing outcome measures (crash severity, speed, violations)
- timeframe: Missing temporal coverage (long-term effects, recent studies)
- geography: Missing geographic contexts (Europe, Asia, North America)

If evidence is sufficient, return empty gaps array.
Return at most 3 gaps, ordered by priority.

JSON ONLY:"""


def analyze_gaps(
    query: str,
    context: str,
    llm,
    model: str
) -> GapAnalysis:
    """
    Analyze context for knowledge gaps.
    
    Args:
        query: Original user question
        context: Current search context
        llm: LLM client
        model: Model to use
        
    Returns:
        GapAnalysis with identified gaps
    """
    # Summarize context to fit in prompt
    context_summary = context[:3000] if len(context) > 3000 else context
    
    prompt = GAP_ANALYSIS_PROMPT.format(
        query=query,
        context_summary=context_summary
    )
    
    try:
        response = llm.generate(
            prompt=prompt,
            system_prompt="You are a research methodology expert analyzing evidence gaps. Respond only with valid JSON.",
            temperature=0.1,
            max_tokens=2000,  # H2: was 500 (4×)
            model=model
        )
        
        # Parse JSON response
        result = _parse_gap_response(response)
        return result
        
    except Exception as e:
        logger.warning(f"Gap analysis failed: {e}")
        # Return default - assume we need full search
        return GapAnalysis(
            has_sufficient_evidence=False,
            confidence_if_answered_now=0.5,
            gaps=[]
        )


def _parse_gap_response(response: str) -> GapAnalysis:
    """Parse LLM response into GapAnalysis."""
    try:
        # Clean response - extract JSON if wrapped in markdown
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:-1])
        
        data = json.loads(response)
        
        gaps = []
        for g in data.get("gaps", []):
            gaps.append(Gap(
                gap_type=g.get("gap_type", "context"),
                description=g.get("description", ""),
                suggested_query=g.get("suggested_query", ""),
                priority=float(g.get("priority", 0.5))
            ))
        
        return GapAnalysis(
            has_sufficient_evidence=data.get("has_sufficient_evidence", False),
            confidence_if_answered_now=float(data.get("confidence_if_answered_now", 0.5)),
            gaps=sorted(gaps, key=lambda g: g.priority, reverse=True)[:3]  # Top 3
        )
        
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse gap analysis JSON: {e}")
        return GapAnalysis(
            has_sufficient_evidence=False,
            confidence_if_answered_now=0.5,
            gaps=[]
        )


def get_follow_up_queries(analysis: GapAnalysis, max_queries: int = 3) -> List[str]:
    """Extract follow-up queries from gap analysis."""
    queries = []
    for gap in analysis.gaps[:max_queries]:
        if gap.suggested_query:
            queries.append(gap.suggested_query)
    return queries


def gaps_to_display_string(gaps: List[Gap]) -> str:
    """Format gaps for display."""
    if not gaps:
        return "No significant gaps identified"
    
    lines = []
    for i, gap in enumerate(gaps, 1):
        lines.append(f"{i}. [{gap.gap_type}] {gap.description}")
    return "\n".join(lines)
