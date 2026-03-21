"""
Time Estimator for RAG Queries.

Calculates expected response time based on user configuration.
"""

from typing import Tuple, Optional


# Base times in seconds for each component
BASE_TIMES = {
    "query_expansion": 5,      # LLM call
    "hyde": 8,                  # LLM call
    "embedding": 0.2,           # GPU - fast
    "vector_search": 0.3,       # CPU - fast
    "reranking_per_10": 1.5,    # GPU - scales with papers
    "context_building": 0.1,    # CPU - fast
    "llm_base": 20,             # Cloud LLM base time
    "llm_per_1000_tokens": 10,  # Token generation time
    "validation": 0.1,          # CPU - fast
}

# Model speed multipliers (cloud models are slower due to network)
MODEL_MULTIPLIERS = {
    "gpt-oss:120b-cloud": 1.3,
    "qwen3-coder:480b-cloud": 1.5,
    "deepseek-v3.1:671b-cloud": 1.6,
    "qwen3-next:80b-cloud": 1.2,
    "minimax-m2:cloud": 1.4,
    "gemma:7b": 0.5,  # Local model - faster
}


def estimate_time(
    depth: str,
    model: str,
    paper_range: Tuple[int, int],
    sequential_thinking: bool = False,
    auto_papers: bool = True
) -> int:
    """
    Estimate total response time in seconds.
    
    Args:
        depth: "Low", "Medium", or "High"
        model: Model name
        paper_range: (min_papers, max_papers)
        sequential_thinking: Whether sequential RAG is enabled
        auto_papers: Whether AI decides paper count
        
    Returns:
        Estimated time in seconds
    """
    total = 0.0
    
    # Depth-based components
    if depth == "Low":
        # Skip HyDE and query expansion
        total += BASE_TIMES["embedding"]
        total += BASE_TIMES["vector_search"]
        max_tokens = 1000
    elif depth == "Medium":
        total += BASE_TIMES["query_expansion"]
        total += BASE_TIMES["hyde"]
        total += BASE_TIMES["embedding"]
        total += BASE_TIMES["vector_search"]
        max_tokens = 2000
    else:  # High
        total += BASE_TIMES["query_expansion"]
        total += BASE_TIMES["hyde"]
        total += BASE_TIMES["embedding"]
        total += BASE_TIMES["vector_search"]
        max_tokens = 3500
    
    # Reranking time (scales with paper count)
    max_papers = paper_range[1]
    rerank_time = (max_papers / 10) * BASE_TIMES["reranking_per_10"]
    total += rerank_time
    
    # Context building
    total += BASE_TIMES["context_building"]
    
    # LLM generation (biggest component)
    llm_time = BASE_TIMES["llm_base"]
    llm_time += (max_tokens / 1000) * BASE_TIMES["llm_per_1000_tokens"]
    
    # Apply model multiplier
    multiplier = MODEL_MULTIPLIERS.get(model, 1.2)
    llm_time *= multiplier
    total += llm_time
    
    # Validation
    total += BASE_TIMES["validation"]
    
    # Sequential thinking adds rounds
    if sequential_thinking:
        total *= 1.6  # ~60% more for additional search round
    
    return int(total)


def format_time_estimate(seconds: int) -> str:
    """
    Format seconds as human-readable time estimate.
    
    Args:
        seconds: Estimated time in seconds
        
    Returns:
        Formatted string like "~30s" or "~1-2 min"
    """
    if seconds < 60:
        return f"~{seconds}s"
    elif seconds < 120:
        return f"~1 min"
    else:
        min_est = seconds // 60
        max_est = min_est + 1
        return f"~{min_est}-{max_est} min"


def get_time_breakdown(
    depth: str,
    model: str, 
    paper_range: Tuple[int, int],
    sequential_thinking: bool = False
) -> dict:
    """
    Get detailed time breakdown for each component.
    
    Returns:
        Dictionary with component times
    """
    breakdown = {}
    
    if depth != "Low":
        breakdown["Query Expansion"] = BASE_TIMES["query_expansion"]
        breakdown["HyDE Generation"] = BASE_TIMES["hyde"]
    
    breakdown["Embedding"] = BASE_TIMES["embedding"]
    breakdown["Vector Search"] = BASE_TIMES["vector_search"]
    
    max_papers = paper_range[1]
    breakdown["Reranking"] = int((max_papers / 10) * BASE_TIMES["reranking_per_10"])
    
    # LLM time
    max_tokens = {"Low": 1000, "Medium": 2000, "High": 3500}[depth]
    llm_time = BASE_TIMES["llm_base"] + (max_tokens / 1000) * BASE_TIMES["llm_per_1000_tokens"]
    multiplier = MODEL_MULTIPLIERS.get(model, 1.2)
    breakdown["LLM Generation"] = int(llm_time * multiplier)
    
    if sequential_thinking:
        breakdown["Sequential Round"] = int(sum(breakdown.values()) * 0.6)
    
    return breakdown
