"""
Sequential RAG Package.

Modular components extracted from the monolithic sequential_rag.py.
"""

from .models import (
    SearchRound,
    SectionResult,
    GenerationProgress,
    is_final_section,
    FINAL_SECTION_PATTERNS
)
from .proofreading import ProofreadingMixin
from .planning import PlanningMixin
from .generation import GenerationMixin
from .search import SearchMixin
from .reflection import ReflectionMixin

__all__ = [
    # Models
    "SearchRound",
    "SectionResult", 
    "GenerationProgress",
    "is_final_section",
    "FINAL_SECTION_PATTERNS",
    # Mixins
    "ProofreadingMixin",
    "PlanningMixin",
    "GenerationMixin",
    "SearchMixin",
    "ReflectionMixin",
]
