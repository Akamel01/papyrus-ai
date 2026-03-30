"""
Extraction configuration with depth-aware fact targets.
Derives chunk and rerank limits from fact targets.

This module implements Scenario 3 (Two-Stage Extraction):
1. max_facts is the PRIMARY configurable parameter
2. max_chunks and top_k_rerank are DERIVED from max_facts
3. Supports depth-aware defaults and section mode adjustments
"""
from dataclasses import dataclass
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExtractionParams:
    """Runtime extraction parameters (derived from config + depth)."""
    max_facts: int              # Target fact count (PRIMARY)
    sample_size: int            # Chunks to sample for density estimation
    density_estimate: float     # Expected facts-per-chunk ratio
    max_chunks: int             # Derived: max_facts / density + buffer
    top_k_rerank: int           # Derived: max_chunks * 1.25
    early_stop_threshold: int   # Derived: max_facts * buffer (when to stop)

    def __repr__(self) -> str:
        return (
            f"ExtractionParams(max_facts={self.max_facts}, "
            f"max_chunks={self.max_chunks}, top_k_rerank={self.top_k_rerank}, "
            f"sample_size={self.sample_size}, density={self.density_estimate:.1f})"
        )


# Default fact targets by depth (used when config doesn't specify)
DEFAULT_MAX_FACTS: Dict[str, int] = {
    "Low": 40,
    "Medium": 80,
    "High": 150,
}

# Section mode per-section targets
DEFAULT_FACTS_PER_SECTION: Dict[str, int] = {
    "Low": 25,
    "Medium": 40,
    "High": 60,
}

# Default extraction settings
DEFAULT_SAMPLE_SIZE = 8
DEFAULT_DENSITY_ESTIMATE = 3.0
DEFAULT_EARLY_STOP_BUFFER = 1.1
DEFAULT_RERANK_BUFFER = 1.25


def get_extraction_params(
    config: Dict[str, Any],
    depth: str,
    section_mode: bool = False,
    section_count: int = 1
) -> ExtractionParams:
    """
    Calculate extraction parameters based on config, depth, and mode.

    The key insight is that `max_facts` is the PRIMARY control:
    - max_chunks = max_facts / estimated_density + sample_buffer
    - top_k_rerank = max_chunks * 1.25

    This ensures we never extract more than needed, reducing waste.

    Args:
        config: Full config dict from config.yaml
        depth: "Low", "Medium", or "High"
        section_mode: Whether generating multiple sections
        section_count: Number of sections (if section_mode=True)

    Returns:
        ExtractionParams with all derived values
    """
    extraction_cfg = config.get("extraction", {})

    # Normalize depth to title case for consistent lookup
    depth = depth.title() if depth else "Medium"
    if depth not in DEFAULT_MAX_FACTS:
        logger.warning(f"Unknown depth '{depth}', defaulting to Medium")
        depth = "Medium"

    # 1. Get base max_facts from config or defaults
    max_facts_cfg = extraction_cfg.get("max_facts", DEFAULT_MAX_FACTS)

    if isinstance(max_facts_cfg, int):
        # Legacy: single value for all depths
        base_max_facts = max_facts_cfg
    elif isinstance(max_facts_cfg, dict):
        # New: depth-aware values (check both lower and title case)
        base_max_facts = (
            max_facts_cfg.get(depth) or
            max_facts_cfg.get(depth.lower()) or
            DEFAULT_MAX_FACTS[depth]
        )
    else:
        base_max_facts = DEFAULT_MAX_FACTS[depth]

    # 2. Adjust for section mode
    if section_mode and section_count > 1:
        # Get section-specific config
        section_cfg = extraction_cfg.get("section_mode", {})
        facts_per_section_cfg = section_cfg.get(
            "facts_per_section", DEFAULT_FACTS_PER_SECTION
        )

        if isinstance(facts_per_section_cfg, int):
            max_facts = facts_per_section_cfg
        elif isinstance(facts_per_section_cfg, dict):
            max_facts = (
                facts_per_section_cfg.get(depth) or
                facts_per_section_cfg.get(depth.lower()) or
                DEFAULT_FACTS_PER_SECTION[depth]
            )
        else:
            max_facts = DEFAULT_FACTS_PER_SECTION[depth]
    else:
        max_facts = base_max_facts

    # 3. Get extraction settings
    sample_size = extraction_cfg.get("sample_size", DEFAULT_SAMPLE_SIZE)
    density_default = extraction_cfg.get("density_estimate_default", DEFAULT_DENSITY_ESTIMATE)
    early_stop_buffer = extraction_cfg.get("early_stop_buffer", DEFAULT_EARLY_STOP_BUFFER)
    rerank_buffer = extraction_cfg.get("rerank_buffer", DEFAULT_RERANK_BUFFER)

    # 4. Derive chunk and rerank limits from max_facts
    # Formula: chunks_needed = facts_wanted / facts_per_chunk + sample_buffer
    base_chunks_needed = int(max_facts / density_default)
    max_chunks = base_chunks_needed + sample_size  # Add sample buffer

    # Rerank should fetch slightly more than we'll process
    top_k_rerank = int(max_chunks * rerank_buffer)

    # Early stop threshold (slight overshoot allowed)
    early_stop_threshold = int(max_facts * early_stop_buffer)

    # 5. Apply safety ceiling from legacy config
    legacy_max = config.get("librarian", {}).get("max_chunks", 150)
    if max_chunks > legacy_max:
        logger.debug(
            f"[Extraction] Capping max_chunks from {max_chunks} to {legacy_max} (safety ceiling)"
        )
        max_chunks = legacy_max
        # Recalculate rerank for capped value
        top_k_rerank = int(max_chunks * rerank_buffer)

    # 6. Ensure sample_size doesn't exceed 1/3 of max_chunks
    effective_sample_size = min(sample_size, max(3, max_chunks // 3))

    params = ExtractionParams(
        max_facts=max_facts,
        sample_size=effective_sample_size,
        density_estimate=density_default,
        max_chunks=max_chunks,
        top_k_rerank=top_k_rerank,
        early_stop_threshold=early_stop_threshold,
    )

    logger.info(
        f"[Extraction] depth={depth}, section_mode={section_mode}, "
        f"max_facts={max_facts}, max_chunks={max_chunks}, "
        f"top_k_rerank={top_k_rerank}, sample={effective_sample_size}"
    )

    return params


def get_depth_fact_targets(config: Dict[str, Any]) -> Dict[str, int]:
    """
    Get the max_facts targets for each depth level.

    Returns:
        Dict mapping depth name to max_facts value
    """
    extraction_cfg = config.get("extraction", {})
    max_facts_cfg = extraction_cfg.get("max_facts", DEFAULT_MAX_FACTS)

    if isinstance(max_facts_cfg, int):
        # Single value for all depths
        return {d: max_facts_cfg for d in DEFAULT_MAX_FACTS}
    elif isinstance(max_facts_cfg, dict):
        # Merge with defaults
        result = dict(DEFAULT_MAX_FACTS)
        for depth in DEFAULT_MAX_FACTS:
            if depth in max_facts_cfg:
                result[depth] = max_facts_cfg[depth]
            elif depth.lower() in max_facts_cfg:
                result[depth] = max_facts_cfg[depth.lower()]
        return result
    else:
        return dict(DEFAULT_MAX_FACTS)
