"""
User Feedback Logging for RAG responses.

Logs thumbs up/down feedback to JSONL file for quality improvement.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

FEEDBACK_FILE = Path("./data/feedback.jsonl")


def log_feedback(
    query: str,
    response: str,
    feedback: str,  # "positive" or "negative"
    model: str,
    depth: str,
    confidence: str,
    sources_count: int,
    response_time_ms: Optional[float] = None,
    user_comment: Optional[str] = None
) -> bool:
    """
    Log user feedback to JSONL file.
    
    Args:
        query: User's question
        response: Generated response (truncated)
        feedback: "positive" or "negative"
        model: LLM model used
        depth: Research depth setting
        confidence: Confidence level
        sources_count: Number of sources used
        response_time_ms: Response generation time
        user_comment: Optional user comment
        
    Returns:
        True if logged successfully
    """
    try:
        # Ensure directory exists
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "query": query,
            "response_preview": response[:500] if response else "",
            "feedback": feedback,
            "model": model,
            "depth": depth,
            "confidence": confidence,
            "sources_count": sources_count,
            "response_time_ms": response_time_ms,
            "user_comment": user_comment
        }
        
        with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        
        logger.info(f"Feedback logged: {feedback} for query '{query[:50]}...'")
        return True
        
    except Exception as e:
        logger.error(f"Failed to log feedback: {e}")
        return False


def get_feedback_stats() -> Dict[str, Any]:
    """
    Get aggregated feedback statistics.
    
    Returns:
        Dictionary with feedback counts and rates
    """
    if not FEEDBACK_FILE.exists():
        return {"total": 0, "positive": 0, "negative": 0, "positive_rate": 0.0}
    
    positive = 0
    negative = 0
    
    try:
        with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    if entry.get("feedback") == "positive":
                        positive += 1
                    elif entry.get("feedback") == "negative":
                        negative += 1
        
        total = positive + negative
        positive_rate = positive / total if total > 0 else 0.0
        
        return {
            "total": total,
            "positive": positive,
            "negative": negative,
            "positive_rate": positive_rate
        }
    except Exception as e:
        logger.error(f"Failed to get feedback stats: {e}")
        return {"total": 0, "positive": 0, "negative": 0, "positive_rate": 0.0}
