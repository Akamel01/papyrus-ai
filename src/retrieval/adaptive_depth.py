"""
Adaptive Depth Controller for Sequential RAG.

Dynamically adjusts search parameters based on query type and initial confidence.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class AdaptiveParams:
    """Dynamically adjusted search parameters."""
    max_rounds: int           # 1-3 search rounds
    reflection_mode: str      # "skip", "quick", "full"
    search_expansion: float   # Multiplier for k values (1.0-2.0)
    description: str          # Human-readable description


def get_adaptive_params(
    query_type: str,
    confidence_score: float,
    user_depth: str = "Medium"
) -> AdaptiveParams:
    """
    Dynamically adjust search parameters based on query characteristics.
    
    Args:
        query_type: From question_classifier ("definition", "comparison", "mechanism", "review", "general")
        confidence_score: From confidence_scorer (0.0-1.0)
        user_depth: User-selected depth ("Low", "Medium", "High")
        
    Returns:
        AdaptiveParams with adjusted settings
    """
    # Base parameters from user depth
    base_rounds = {"Low": 1, "Medium": 2, "High": 3}
    max_rounds = base_rounds.get(user_depth, 2)
    
    # Adjust based on query type
    if query_type == "definition":
        # Simple definition queries don't need multi-round
        return AdaptiveParams(
            max_rounds=1,
            reflection_mode="skip",
            search_expansion=1.0,
            description="Definition query - single search sufficient"
        )
    
    elif query_type == "comparison":
        # Comparison needs multiple perspectives but not exhaustive
        if confidence_score >= 0.75:
            return AdaptiveParams(
                max_rounds=1,
                reflection_mode="skip",
                search_expansion=1.0,
                description="Comparison with good initial coverage"
            )
        else:
            return AdaptiveParams(
                max_rounds=2,
                reflection_mode="quick",
                search_expansion=1.2,
                description="Comparison needs broader search"
            )
    
    elif query_type == "review":
        # Review queries need comprehensive coverage
        if confidence_score >= 0.85:
            return AdaptiveParams(
                max_rounds=2,
                reflection_mode="quick",
                search_expansion=1.5,
                description="Review with strong initial results"
            )
        else:
            return AdaptiveParams(
                max_rounds=3,
                reflection_mode="full",
                search_expansion=2.0,
                description="Review needs comprehensive multi-round search"
            )
    
    elif query_type == "mechanism":
        # Mechanism/relationship queries need depth
        if confidence_score >= 0.70:
            return AdaptiveParams(
                max_rounds=2,
                reflection_mode="quick",
                search_expansion=1.3,
                description="Mechanism question with decent coverage"
            )
        else:
            return AdaptiveParams(
                max_rounds=2,
                reflection_mode="full",
                search_expansion=1.5,
                description="Mechanism question needs focused follow-up"
            )
    
    else:  # "general" or unknown
        # General questions - use confidence to decide
        if confidence_score >= 0.85:
            return AdaptiveParams(
                max_rounds=1,
                reflection_mode="skip",
                search_expansion=1.0,
                description="High confidence - direct answer"
            )
        elif confidence_score >= 0.65:
            return AdaptiveParams(
                max_rounds=min(2, max_rounds),
                reflection_mode="quick",
                search_expansion=1.2,
                description="Medium confidence - quick expansion"
            )
        else:
            return AdaptiveParams(
                max_rounds=max_rounds,
                reflection_mode="full",
                search_expansion=1.5,
                description="Low confidence - full sequential thinking"
            )


def should_continue_searching(
    current_round: int,
    params: AdaptiveParams,
    current_confidence: float
) -> bool:
    """
    Determine if another search round is needed.
    
    Args:
        current_round: Current round number (1-indexed)
        params: Adaptive parameters
        current_confidence: Current confidence score
        
    Returns:
        True if should continue, False otherwise
    """
    # Reached max rounds
    if current_round >= params.max_rounds:
        return False
    
    # Confidence is now high enough
    if current_confidence >= 0.85:
        return False
    
    # Skip mode never continues
    if params.reflection_mode == "skip":
        return False
    
    return True


def get_expanded_k_values(
    base_initial_k: int,
    base_rerank_k: int,
    expansion: float
) -> tuple:
    """
    Get expanded k values based on search expansion multiplier.
    
    Returns:
        Tuple of (initial_k, rerank_k)
    """
    return (
        int(base_initial_k * expansion),
        int(base_rerank_k * expansion)
    )
