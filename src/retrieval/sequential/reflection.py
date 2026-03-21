"""
Reflection Mixin for Sequential RAG.

LLM reflection and follow-up logic:
- Chain of thought reflection
- Follow-up query decision
- Summary and log methods
"""

import re
import logging
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


class ReflectionMixin:
    """
    Mixin providing LLM reflection capabilities.
    
    Requires:
        - self.pipeline with "llm" key
        - self.reflection_log list for logging decisions
    """
    
    def _ask_for_more_info(
        self,
        original_query: str,
        context: str,
        model: str
    ) -> Tuple[Optional[str], str]:
        """
        Ask LLM if it needs more specific information using Chain of Thought.
        
        Returns:
            Tuple: (Follow-up search query or None, Reasoning string)
        """
        llm = self.pipeline["llm"]
        
        # PROMPT WITH CHAIN OF THOUGHT STRUCTURE
        reflection_prompt = f"""You are a senior research methodology expert. 
Review the user's question and the initial search results.

User Question: {original_query}

Available Context Summary (first 3000 chars):
{context[:3000]}

TASK:
1. Analyze if the context provides specific, concrete data to answer the KEY aspects of the user's question.
2. Identify any missing specific details, statistics, or comparisons.

RESPONSE FORMAT:
You MUST respond in this exact format:

THOUGHT: [Brief critical analysis of what is missing or confirming sufficiency]
DECISION: [FOLLOW_UP "search query" | SUFFICIENT]

Examples:
THOUGHT: The context covers general effects but lacks specific percentage data for the Halo Effect.
DECISION: FOLLOW_UP "Halo Effect site specific percentage reductions"

THOUGHT: The context defines the Crash Cost formula fully including societal factors.
DECISION: SUFFICIENT

Response:"""

        try:
            response = llm.generate(
                prompt=reflection_prompt,
                system_prompt="You are a critical researcher. Always look for gaps.",
                temperature=0.2,
                max_tokens=600,  # H2: was 150 (4×)
                model=model
            )
            
            response = response.strip()
            
            # Parse THOUGHT and DECISION
            response = response.replace("\r\n", "\n")
            
            # Flexible regex for decision
            decision_match = re.search(r"(?:DECISION|Decision):\s*(.*)", response, re.DOTALL)
            decision_line = decision_match.group(1).strip() if decision_match else ""
            
            # Flexible regex for thought
            thought_match = re.search(r"(?:THOUGHT|Thought|REASONING|Reasoning):\s*(.*?)(?=\n.*(?:DECISION|Decision):|$)", response, re.DOTALL)
            
            if thought_match:
                thought = thought_match.group(1).strip()
            elif decision_match:
                thought = response[:decision_match.start()].strip()
            else:
                thought = "Reasoning implied in decision."
                decision_line = response
            
            if not thought:
                thought = "No specific reasoning provided."
            
            # Check decision
            is_sufficient = "SUFFICIENT" in decision_line.upper()
            
            if is_sufficient:
                return None, thought
            
            # Extract query from FOLLOW_UP "query"
            query_match = re.search(r'(?:FOLLOW_UP|Follow_up).*?["\'](.+?)["\']', decision_line, re.IGNORECASE)
            if not query_match:
                query_match = re.search(r"(?:FOLLOW_UP|Follow_up)\s*(.*)", decision_line, re.IGNORECASE)
                
            follow_up_query = query_match.group(1).strip() if query_match else None
            
            if follow_up_query:
                return follow_up_query[:200], thought
            
            return None, thought
            
        except Exception as e:
            logger.warning(f"Reflection failed: {e}")
            self.reflection_log.append({
                "round": len(self.search_history),
                "decision": "error",
                "message": str(e)
            })
            return None, f"Reflection error: {e}"
    
    def get_search_summary(self) -> str:
        """Get summary of search rounds for display."""
        if not self.search_history:
            return "No searches performed"
        
        lines = [f"🔄 Sequential RAG: {len(self.search_history)} round(s)"]
        for sr in self.search_history:
            lines.append(f"  Round {sr.round_number}: '{sr.query[:50]}...' → {sr.result_count} results")
        
        return "\n".join(lines)
    
    def get_reflection_log(self) -> List[Dict]:
        """Get the log of reflection decisions for UI display."""
        return self.reflection_log.copy()
