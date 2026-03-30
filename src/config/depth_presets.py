"""
Depth Preset Configuration for Research Queries.

Defines hyperparameters for Low/Medium/High research depth levels.
"""

from typing import Dict, Any


DEPTH_PRESETS: Dict[str, Dict[str, Any]] = {
    "Low": {
        "description": "Quick answer - 10 papers, fast response",
        "min_unique_papers": 10,
        "max_per_doi": 2,            # H3: was 5
        "sub_query_limit": (1, 2),   # Strict Limit: 1-2 sub-queries
        "top_k_initial": 25,         # H1: was 100 — per query/sub-query
        "top_k_rerank": 20,          # H1: was 50
        "top_k_final": 15,           # H1: was 30
        "max_tokens": 12000,         # H2: was 3000 (4×)
        "use_hyde": False,           # Skip HyDE for speed
        "use_query_expansion": False,  # Skip expansion for speed
        "temperature": 0.1,
        # Extraction targets (Scenario 3: fact-driven limits)
        "target_facts": 40,          # Max facts for single response
        "facts_per_section": 25,     # Max facts per section in section mode
        "search_params": {
            "ef_search": 128,      # Standard speed
            "oversampling": 2.0,
            "use_quantization": True
        }
    },
    "Medium": {
        "description": "Balanced - 25 papers, comprehensive answer",
        "min_unique_papers": 25,
        "max_per_doi": 3,            # H3: was 10
        "sub_query_limit": (1, 3),   # Strict Limit: 2-4 sub-queries
        "top_k_initial": 50,         # H1: was 200 — per query/sub-query
        "top_k_rerank": 40,          # H1: was 100
        "top_k_final": 35,           # H1: was 70
        "max_tokens": 24000,         # H2: was 6000 (4×)
        "use_hyde": True,
        "use_query_expansion": True,
        "temperature": 0.1,
        # Extraction targets (Scenario 3: fact-driven limits)
        "target_facts": 80,          # Max facts for single response
        "facts_per_section": 40,     # Max facts per section in section mode
        "search_params": {
            "ef_search": 200,      # Better recall
            "oversampling": 2.5,
            "use_quantization": True
        }
    },
    "High": {
        "description": "Deep dive - 50 papers, thorough synthesis",
        "min_unique_papers": 50,
        "max_per_doi": 5,            # H3: was 15
        "sub_query_limit": (2, 4),   # Strict Limit: 4-7 sub-queries
        "top_k_initial": 120,        # H1: was 100 — per query/sub-query
        "top_k_rerank": 100,          # H1: was 75
        "top_k_final": 80,           # H1: was 75
        "max_tokens": 42000,         # H2: was 10500 (4×)
        "use_hyde": True,
        "use_query_expansion": True,
        "temperature": 0.2,          # H3: was 0.05
        # Extraction targets (Scenario 3: fact-driven limits)
        "target_facts": 150,         # Max facts for single response
        "facts_per_section": 60,     # Max facts per section in section mode
        "search_params": {
            "ef_search": 1200,      # Maximum recall (Deep Search)
            "oversampling": 4.0,   # Heavy oversampling for quantization correction
            "use_quantization": True
        }
    }
}


def get_depth_preset(depth: str) -> Dict[str, Any]:
    """
    Get hyperparameters for a given depth level.
    
    Args:
        depth: "Low", "Medium", or "High"
        
    Returns:
        Dictionary of hyperparameters
    """
    return DEPTH_PRESETS.get(depth, DEPTH_PRESETS["Medium"])


def get_depth_options() -> list:
    """Get list of available depth options for UI."""
    return list(DEPTH_PRESETS.keys())


def get_depth_descriptions() -> Dict[str, str]:
    """Get descriptions for each depth level."""
    return {k: v["description"] for k, v in DEPTH_PRESETS.items()}


def resolve_paper_target(
    depth: str,
    user_range: tuple = None,
    let_ai_decide: bool = True
) -> tuple:
    """
    Resolve the target paper count based on depth and user settings.
    
    This is the SINGLE SOURCE OF TRUTH for target paper count.
    All components should call this function.
    
    Args:
        depth: "Low", "Medium", or "High"
        user_range: User-specified (min, max) tuple, or None
        let_ai_decide: If True, use depth preset; if False, use user_range
        
    Returns:
        Tuple of (target_papers, paper_range, warning_message)
        - target_papers: The target number of unique papers
        - paper_range: (min, max) tuple for searching
        - warning_message: Optional mismatch warning, or None
    """
    preset = DEPTH_PRESETS.get(depth, DEPTH_PRESETS["Medium"])
    depth_target = preset["min_unique_papers"]
    
    if let_ai_decide or user_range is None:
        # Use depth preset
        target = depth_target
        paper_range = (int(target * 0.6), int(target * 1.4))
        return target, paper_range, None
    
    # User specified range
    user_min, user_max = user_range
    user_midpoint = (user_min + user_max) // 2
    target = user_midpoint
    
    # Check for mismatch
    warning = None
    if user_midpoint < depth_target * 0.7:
        warning = f"⚠️ Selected range ({user_min}-{user_max}) may be too narrow for {depth} depth (recommended: ~{depth_target})"
    elif user_midpoint > depth_target * 1.5:
        warning = f"⚠️ Selected range ({user_min}-{user_max}) exceeds typical for {depth} depth (recommended: ~{depth_target})"
    
    return target, user_range, warning

