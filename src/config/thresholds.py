"""
Centralized Thresholds Configuration.

Single source of truth for all numeric thresholds used across the application.
"""

# Confidence level thresholds based on unique paper count
# Format: (threshold, label)
CONFIDENCE_THRESHOLDS = {
    "HIGH": 10,     # >= 10 unique papers = HIGH confidence
    "MEDIUM": 5,    # >= 5 unique papers = MEDIUM confidence
    # Below 5 = LOW confidence
}

# RRF (Reciprocal Rank Fusion) constant
RRF_K = 60

# Paper count thresholds for sequential RAG decisions
SEQUENTIAL_FORCE_FOLLOWUP_THRESHOLD = 8   # Force follow-up if < 8 papers found
SEQUENTIAL_OVERRIDE_THRESHOLD = 12        # Override "SUFFICIENT" if < 12 papers

# Context similarity deduplication threshold
CONTEXT_SIMILARITY_THRESHOLD = 0.8

# Default paper retrieval multipliers
INITIAL_SEARCH_MULTIPLIER = 5   # Get 5x max_papers as candidates
RERANK_MULTIPLIER = 2           # Rerank 2x max_papers


def get_confidence_level(unique_paper_count: int) -> str:
    """
    Get confidence level based on unique paper count.
    
    Args:
        unique_paper_count: Number of unique papers/DOIs in results
        
    Returns:
        "HIGH", "MEDIUM", or "LOW"
    """
    if unique_paper_count >= CONFIDENCE_THRESHOLDS["HIGH"]:
        return "HIGH"
    elif unique_paper_count >= CONFIDENCE_THRESHOLDS["MEDIUM"]:
        return "MEDIUM"
    else:
        return "LOW"
