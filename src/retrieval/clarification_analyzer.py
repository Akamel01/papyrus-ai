"""
Clarification Analyzer for Sequential RAG.

Analyzes user queries and generates clarifying questions before search.
"""

import json
import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ClarificationQuestion:
    """A clarifying question to ask the user."""
    question: str
    question_type: str  # "scope", "timeframe", "context", "include", "exclude"
    options: List[str]  # Suggested answers (empty for free text)
    required: bool
    default: Optional[str] = None


@dataclass
class ClarificationAnalysis:
    """Analysis of whether query needs clarification."""
    needs_clarification: bool
    questions: List[ClarificationQuestion]
    can_proceed_without: bool  # True if questions are optional


CLARIFICATION_PROMPT = """Analyze this research question and determine if clarification is needed before searching.

QUESTION: {query}

Determine if clarification would significantly improve the search. Only ask clarifying questions if they would meaningfully narrow the scope and improve relevance.

Respond with ONLY valid JSON in this format:
{{
    "needs_clarification": true/false,
    "can_proceed_without": true/false,
    "questions": [
        {{
            "question_type": "scope|timeframe|context|include|exclude",
            "question": "The question to ask",
            "options": ["Option 1", "Option 2"] or [] for free text,
            "required": true/false,
            "default": "default option or null"
        }}
    ]
}}

Question types:
- scope: Level of detail (brief overview vs comprehensive review)
- timeframe: Publication year range
- context: Specific settings (urban, rural, highway, etc.)
- include: Topics that must be included
- exclude: Topics to exclude

Rules:
- Max 3 questions
- Don't ask clarification for simple definition queries
- For review queries, ask about scope and timeframe
- Prefer questions with predefined options over free text

JSON ONLY:"""


def analyze_for_clarification(
    query: str,
    llm,
    model: str
) -> ClarificationAnalysis:
    """
    Analyze if query needs clarification before searching.
    
    Args:
        query: User's research question
        llm: LLM client
        model: Model to use
        
    Returns:
        ClarificationAnalysis with questions if needed
    """
    # Quick heuristics - skip clarification for simple queries
    if _is_simple_query(query):
        return ClarificationAnalysis(
            needs_clarification=False,
            questions=[],
            can_proceed_without=True
        )
    
    prompt = CLARIFICATION_PROMPT.format(query=query)
    
    try:
        response = llm.generate(
            prompt=prompt,
            system_prompt="You are a research assistant helping to clarify user questions. Respond only with valid JSON.",
            temperature=0.1,
            max_tokens=1600,  # H2: was 400 (4×)
            model=model
        )
        
        return _parse_clarification_response(response)
        
    except Exception as e:
        logger.warning(f"Clarification analysis failed: {e}")
        return ClarificationAnalysis(
            needs_clarification=False,
            questions=[],
            can_proceed_without=True
        )


def _is_simple_query(query: str) -> bool:
    """Check if query is simple enough to skip clarification."""
    query_lower = query.lower()
    
    # Simple definition queries
    simple_patterns = [
        "what is ",
        "what are ",
        "define ",
        "definition of ",
        "meaning of ",
    ]
    
    for pattern in simple_patterns:
        if query_lower.startswith(pattern) and len(query.split()) <= 10:
            return True
    
    # Very short queries
    if len(query.split()) <= 5:
        return True
    
    return False


def _parse_clarification_response(response: str) -> ClarificationAnalysis:
    """Parse LLM response into ClarificationAnalysis."""
    try:
        # Clean response
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:-1])
        
        data = json.loads(response)
        
        questions = []
        for q in data.get("questions", [])[:3]:  # Max 3
            questions.append(ClarificationQuestion(
                question=q.get("question", ""),
                question_type=q.get("question_type", "context"),
                options=q.get("options", []),
                required=q.get("required", False),
                default=q.get("default")
            ))
        
        return ClarificationAnalysis(
            needs_clarification=data.get("needs_clarification", False),
            questions=questions,
            can_proceed_without=data.get("can_proceed_without", True)
        )
        
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse clarification JSON: {e}")
        return ClarificationAnalysis(
            needs_clarification=False,
            questions=[],
            can_proceed_without=True
        )


def build_refined_query(
    original_query: str,
    responses: dict
) -> str:
    """
    Build refined query incorporating user's clarification responses.
    
    Args:
        original_query: Original user question
        responses: Dict of question_type -> user response
        
    Returns:
        Refined query string
    """
    additions = []
    
    if responses.get("timeframe"):
        additions.append(f"published between {responses['timeframe']}")
    
    if responses.get("context"):
        additions.append(f"in {responses['context']} contexts")
    
    if responses.get("include"):
        additions.append(f"including {responses['include']}")
    
    if responses.get("exclude"):
        additions.append(f"excluding {responses['exclude']}")
    
    if additions:
        return f"{original_query} ({', '.join(additions)})"
    
    return original_query


# Predefined question templates for common scenarios
COMMON_QUESTIONS = {
    "scope": ClarificationQuestion(
        question="What level of detail do you need?",
        question_type="scope",
        options=["Brief overview (5-10 papers)", "Standard analysis (10-20 papers)", "Comprehensive review (20-50 papers)"],
        required=False,
        default="Standard analysis (10-20 papers)"
    ),
    "timeframe": ClarificationQuestion(
        question="Any publication year preference?",
        question_type="timeframe",
        options=["Last 5 years (2020-2024)", "Last 10 years (2015-2024)", "All years", "Specific range"],
        required=False,
        default="All years"
    ),
    "context": ClarificationQuestion(
        question="Any specific context or setting?",
        question_type="context",
        options=["Urban intersections", "Rural highways", "School zones", "Work zones", "All contexts"],
        required=False,
        default="All contexts"
    ),
}
