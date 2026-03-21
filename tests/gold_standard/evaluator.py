
"""
Gold Standard Evaluator.

This module implements the "Judge" for the optimization loop.
It uses the target LLM to grade content against the 10 Publication Quality Standards.
"""

import json
import logging
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass

from src.core.interfaces import LLMClient

logger = logging.getLogger(__name__)

@dataclass
class EvaluationResult:
    total_score: int
    criteria_scores: Dict[str, int]
    feedback: Dict[str, str]
    weakest_criterion: str
    pass_status: bool

class CriteriaComplianceMatrix:
    """
    The Judge. Grades text against the 10 Gold Standard Criteria.
    """
    
    CRITERIA = [
        "1. Authoritative Coverage",
        "2. Analytical Depth",
        "3. Conceptual Organization",
        "4. Research Gap Positioning",
        "5. Alignment with Objectives",
        "6. Methodological Literacy",
        "7. Balance & Fairness",
        "8. Synthesis & Insight",
        "9. Precision & Tone",
        "10. Currency & Relevance"
    ]
    
    def __init__(self, llm_client: LLMClient, model_name: str = "gpt-oss:120b-cloud"):
        self.llm = llm_client
        self.model_name = model_name
        
    def grade_output(self, text: str, query: str) -> EvaluationResult:
        """
        Grade the provided academic text.
        """
        logger.info(f"👨‍⚖️ Grading output for query: {query[:50]}...")
        
        prompt = f"""EVALUATION TASK: Grade the following academic text against the 10 Gold Standard Criteria.

QUERY: "{query}"

TEXT TO EVALUATE:
{text[:15000]} ... [truncated if too long]

CRITERIA & SCORING (1-10 Scale):
1. **Authority**: Does it cite canonical/expert sources? (10=Seminal, 1=Random)
2. **Analysis**: Is it analytical (comparing/contrasting) or just descriptive (listing)? (10=Deep Insight, 1=List)
3. **Organization**: Is it structured by CONCEPT or by AUTHOR? (10=Concept-First, 1=He said/She said)
4. **Gap**: Does it explicitly identify valid limitations/unknowns? (10=Inevitable Gap, 1=No Gap)
5. **Alignment**: Does it answer the specific query? (10=Perfect, 1=Irrelevant)
6. **Methodology**: Does it mention study methods (e.g. "Simulation", "Survey")? (10=High Literacy, 1=No Methods)
7. **Balance**: Does it present opposing views? (10=Balanced, 1=Biased)
8. **Synthesis**: Are sentences synthesizing multiple sources? (10=High Synthesis, 1=One citation per sentence)
9. **Precision**: Is the tone scholarly and hedged? (10=Precise, 1=Vague/Hype)
10. **Currency**: Are recent (last 3-5 years) papers included? (10=Modern, 1=Outdated)

INSTRUCTIONS:
- Be strict. A score of 10 requires publication quality.
- Return valid JSON only.

JSON FORMAT:
{{
    "scores": {{
        "Authoritative Coverage": 8,
        "Analytical Depth": 4,
        ...
    }},
    "feedback": {{
        "Authoritative Coverage": "Good usage of Hauer (1997).",
        "Analytical Depth": "Too descriptive. Paragraph 2 is just a list.",
        ...
    }},
    "weakest_link": "Analytical Depth"
}}"""

        try:
            response = self.llm.generate(
                prompt=prompt,
                system_prompt="You are an Elite Academic Reviewer. Grade strictly.",
                temperature=0.0,
                max_tokens=1000,
                model=self.model_name
            )
            
            # Parse JSON
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            cleaned = cleaned.strip()
            
            data = json.loads(cleaned)
            
            scores = data.get("scores", {})
            feedback = data.get("feedback", {})
            weakest = data.get("weakest_link", "Unknown")
            
            # Calculate total
            total = sum(scores.values())
            # Pass if all are PERFECT 10s (Gold Standard Strict Mode)
            has_passed = all(s == 10 for s in scores.values())
            
            logger.info(f"👨‍⚖️ Grading Complete. Score: {total}/100. Pass: {has_passed} (Strict 10/10 Mode)")
            
            return EvaluationResult(
                total_score=total,
                criteria_scores=scores,
                feedback=feedback,
                weakest_criterion=weakest,
                pass_status=has_passed
            )
            
        except Exception as e:
            logger.error(f"Grading failed: {e}")
            return EvaluationResult(0, {}, {}, "Error", False)
