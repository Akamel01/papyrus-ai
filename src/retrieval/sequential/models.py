"""
Data Models for Sequential RAG.

Contains dataclasses used across the sequential RAG modules.
"""

import re
from typing import List, Dict, Set
from dataclasses import dataclass, field


# ==================== FINAL SECTION DETECTION ====================
# Patterns to detect final/summary sections that should be deferred
# These sections are generated AFTER proofreading for better synthesis quality
FINAL_SECTION_PATTERNS = [
    r'(?i)\bconclusion',
    r'(?i)\bsummary',
    r'(?i)\brecommendation',
    r'(?i)\bkey\s*finding',
    r'(?i)\bsynthesis',
    r'(?i)\bfinal\s*remark',
    r'(?i)\bimplication',
    r'(?i)\btakeaway',
]


def is_final_section(title: str) -> bool:
    """
    Check if section title indicates a summary/conclusion section.
    
    These sections should be generated AFTER proofreading to ensure
    they accurately synthesize the finalized content.
    
    Args:
        title: Section title to check
        
    Returns:
        True if title matches final section patterns
    """
    for pattern in FINAL_SECTION_PATTERNS:
        if re.search(pattern, title):
            return True
    return False


@dataclass
class SearchRound:
    """Represents one round of search in sequential RAG."""
    round_number: int
    query: str
    context: str
    result_count: int


from src.core.interfaces import SectionResult


@dataclass
class GenerationProgress:
    """Progress update for streaming section-by-section generation."""
    type: str           # "warning" | "outline" | "section" | "conclusion" | "complete"
    title: str          # Section title (if applicable)
    content: str        # Generated content
    section_num: int    # Current section number
    total_sections: int # Total sections planned
