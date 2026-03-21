"""
Progress Configuration for Live Monitoring UI.

Defines pill configurations, weights, and sub-pills for all 4 configuration modes:
- Config A: Simple Mode (Low Depth, Sequential OFF)
- Config B: Standard Mode (Med/High Depth, Sequential OFF)
- Config C: Sequential Mode (Section OFF)
- Config D: Section Mode (Sequential ON + Section ON)
"""

from typing import Dict, List, Tuple, Optional

# Type aliases
SubPill = Tuple[str, float]  # (name, weight_within_phase)
PillConfig = Dict[str, any]


PROGRESS_CONFIGS: Dict[str, PillConfig] = {
    # Config A: Simple Mode (Low Depth, Sequential OFF)
    "simple": {
        "main_pills": ["Searching", "Generating", "Validating"],
        "weights": [0.25, 0.65, 0.10],
        "sub_pills": {
            "Searching": [
                ("Semantic Search", 0.60),
                ("BM25 Search", 0.40)
            ],
            "Generating": [
                ("Context Building", 0.15),
                ("LLM Generation", 0.85)
            ],
            "Validating": [
                ("Citation Check", 0.70),
                ("Reference Format", 0.30)
            ]
        }
    },
    
    # Config B: Standard Mode (Med/High Depth, Sequential OFF)
    "standard": {
        "main_pills": ["Expanding", "Searching", "Reranking", "Generating", "Validating"],
        "weights": [0.05, 0.20, 0.05, 0.60, 0.10],
        "sub_pills": {
            "Expanding": [
                ("Complexity Check", 0.30),
                ("Query Decomposition", 0.70)
            ],
            "Searching": [
                ("HyDE Generation", 0.25),
                ("Semantic Search", 0.45),
                ("BM25 Search", 0.30)
            ],
            "Reranking": [
                ("Cross-Encoder", 1.00)
            ],
            "Generating": [
                ("Context Building", 0.10),
                ("LLM Generation", 0.90)
            ],
            "Validating": [
                ("Citation Check", 0.70),
                ("Reference Format", 0.30)
            ]
        }
    },
    
    # Config C: Sequential Mode (Section OFF)
    "sequential": {
        "main_pills": ["Expanding", "Searching", "Reflecting", "Generating", "Validating"],
        "weights": [0.05, 0.20, 0.10, 0.55, 0.10],
        "sub_pills": {
            "Expanding": [
                ("Complexity Check", 0.30),
                ("Query Decomposition", 0.70)
            ],
            "Searching": [
                ("HyDE Generation", 0.20),
                ("Round 1 Search", 0.50),
                ("Reranking", 0.30)
            ],
            "Reflecting": [
                ("Context Analysis", 0.40),
                ("Follow-up Decision", 0.30),
                ("Round 2 Search", 0.30)  # Conditional
            ],
            "Generating": [
                ("Context Building", 0.10),
                ("LLM Generation", 0.90)
            ],
            "Validating": [
                ("Citation Check", 0.70),
                ("Reference Format", 0.30)
            ]
        }
    },
    
    # Config D: Section Mode (Sequential ON + Section ON)
    "section": {
        "main_pills": ["🔍 Discovery", "🗺️ Planning", "✍️ Writing", "✅ Finalizing"],
        "weights": [0.12, 0.08, 0.70, 0.10],
        "sub_pills": {
            "🔍 Discovery": [
                ("Query Expansion", 0.08),
                ("HyDE Generation", 0.17),
                ("Phase 1 Search", 0.33),
                ("Reranking", 0.17),
                ("Reactive Audit", 0.17),
                ("Targeted Search", 0.08)  # Conditional
            ],
            "🗺️ Planning": [
                ("Topic Analysis", 0.50),
                ("Section Design", 0.50)
            ],
            "✍️ Writing": [
                ("Section Prep", 0.10),
                ("Generating", 0.60),
                ("Copy-Edit", 0.30)
            ],
            "✅ Finalizing": [
                ("Conclusion", 0.50),
                ("Validation", 0.30),
                ("References", 0.20)
            ]
        }
    }
}


def get_config_name(depth: str, sequential: bool, section_mode: bool) -> str:
    """
    Determine which configuration to use based on settings.
    
    Args:
        depth: "Low", "Medium", or "High"
        sequential: Whether Sequential Thinking is enabled
        section_mode: Whether Section Mode is enabled
        
    Returns:
        Config name: "simple", "standard", "sequential", or "section"
    """
    if section_mode:
        return "section"
    elif sequential:
        return "sequential"
    elif depth in ["Medium", "High"]:
        return "standard"
    else:
        return "simple"


def get_config(config_name: str) -> PillConfig:
    """Get configuration by name."""
    return PROGRESS_CONFIGS.get(config_name, PROGRESS_CONFIGS["simple"])


def get_main_pill_key(pill_name: str) -> str:
    """
    Extract the key for sub-pill lookup from a main pill name.
    Handles emojis and dynamic text like "Writing (3/6)".
    """
    # Keep emoji prefix if present for matching
    if pill_name.startswith(("🔍", "🗺️", "✍️", "✅")):
        # Return the full emoji + first word for matching
        parts = pill_name.split()
        if len(parts) >= 2:
            return f"{parts[0]} {parts[1].rstrip('(')}"
        return pill_name
    
    # For non-emoji pills, just take first word
    return pill_name.split()[0]


def calculate_progress(
    config_name: str,
    main_idx: int,
    sub_idx: int,
    section_current: int = 0,
    section_total: int = 1
) -> float:
    """
    Calculate realistic progress percentage based on weighted phases.
    
    Args:
        config_name: Which config to use
        main_idx: Index of current main pill (0-based)
        sub_idx: Index of current sub-pill within main pill (0-based)
        section_current: For Section Mode, current section number (1-based)
        section_total: For Section Mode, total number of sections
        
    Returns:
        Progress as percentage (0-100)
    """
    config = get_config(config_name)
    weights = config["weights"]
    main_pills = config["main_pills"]
    sub_pills = config["sub_pills"]
    
    if main_idx >= len(weights):
        return 100.0
    
    # Sum completed main pill weights
    progress = sum(weights[:main_idx])
    
    # Get current main pill info
    current_main = main_pills[main_idx]
    main_weight = weights[main_idx]
    pill_key = get_main_pill_key(current_main)
    current_subs = sub_pills.get(pill_key, [])
    
    if not current_subs:
        return progress * 100
    
    # Special handling for Writing phase with sections
    if "Writing" in current_main and section_total > 0 and config_name == "section":
        # Each section contributes equally to the Writing phase
        section_weight = main_weight / section_total
        
        # Add completed sections
        progress += section_weight * (section_current - 1) if section_current > 0 else 0
        
        # Add progress within current section's sub-pills
        if section_current > 0:
            sub_weights = [w for _, w in current_subs]
            total_sub_weight = sum(sub_weights)
            completed_sub_weight = sum(sub_weights[:sub_idx])
            progress += section_weight * (completed_sub_weight / total_sub_weight)
    else:
        # Standard sub-pill progress
        sub_weights = [w for _, w in current_subs]
        total_sub_weight = sum(sub_weights)
        completed_sub_weight = sum(sub_weights[:sub_idx])
        progress += main_weight * (completed_sub_weight / total_sub_weight)
    
    return min(progress * 100, 100.0)


def get_step_to_subpill_mapping(config_name: str) -> Dict[str, Tuple[int, int]]:
    """
    Map step names to (main_pill_idx, sub_pill_idx).
    Used to update progress when a step completes.
    
    Returns:
        Dict mapping step name to (main_idx, sub_idx)
    """
    config = get_config(config_name)
    mapping = {}
    
    for main_idx, main_pill in enumerate(config["main_pills"]):
        pill_key = get_main_pill_key(main_pill)
        subs = config["sub_pills"].get(pill_key, [])
        
        for sub_idx, (sub_name, _) in enumerate(subs):
            # Map both exact name and variations
            mapping[sub_name] = (main_idx, sub_idx)
            mapping[sub_name.lower()] = (main_idx, sub_idx)
            # Also map common step tracker names
            mapping[sub_name.replace(" ", "_").lower()] = (main_idx, sub_idx)
    
    return mapping
