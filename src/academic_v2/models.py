from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum

class MethodologyType(str, Enum):
    EMPIRICAL = "empirical"
    THEORETICAL = "theoretical"
    REVIEW = "review"
    SIMULATION = "simulation"
    CASE_STUDY = "case_study"
    OTHER = "other"

class CertaintyLevel(str, Enum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"

class RhetoricalRole(str, Enum):
    ESTABLISH_TERRITORY = "establish_territory"
    IDENTIFY_GAP = "identify_gap"
    COUNTER_CLAIM = "counter_claim"
    SYNTHESIS = "synthesis"
    SUPPORT = "support"
    CONCLUSION = "conclusion"

    @staticmethod
    def comparison_synonyms() -> set:
        return {"comparison", "counter_claim", "contrast", "evaluation", "critique"}

    @staticmethod
    def background_synonyms() -> set:
        return {"background", "context", "literature_review", "establish_territory", "methodology", "introduction"}

    @staticmethod
    def gap_synonyms() -> set:
        return {"gap", "limitations", "future_work", "identify_gap", "problem_statement", "research_gap"}

class Methodology(BaseModel):
    """
    Captures the methodological context of a finding (Crit 6).
    """
    type: MethodologyType
    context: str = Field(description="Sample size, setting, or specific algorithm used (e.g. 'n=500 rural drivers')")
    limitations: List[str] = Field(default=[], description="Explicit limitations mentioned in the source")

class AtomicFact(BaseModel):
    """
    A discrete unit of evidence extracted from a source text (Step 1 Output).
    """
    id: str = Field(description="Unique hash of the claim")
    source_id: str = Field(description="ID of the original paper/source")
    
    # The Core Extraction
    claim_text: str = Field(description="The independent finding or statement")
    excerpt_quote: str = Field(description="Verbatim text from source for verification")
    
    # Methodological Literacy (Crit 6)
    methodology: Methodology
    
    # Conceptual Organization (Crit 3)
    topics: List[str] = Field(description="Thematic tags (e.g. ['safety', 'speed_limit'])")
    
    # Tone & Balance (Crit 9, 7)
    certainty: CertaintyLevel
    
    # Full APA reference string (C5 FIX: was silently dropped by Pydantic)
    citation: str = Field(default="", description="Full APA reference string for this source")
    
    # Metadata
    year: int = Field(description="Year of publication")

class ParagraphPlan(BaseModel):
    """
    A logical blueprint for a single paragraph (Step 2 Output).
    """
    order: int
    section_name: str = Field(description="The section this paragraph belongs to")
    
    # The "Point" (Crit 2 - Analytical)
    thesis_statement: str = Field(description="The main argument of this paragraph")
    
    # Rhetorical Move (Crit 4 - Position Gap)
    rhetorical_role: RhetoricalRole
    
    # Evidence Assignment (Crit 1 - Coverage)
    assigned_evidence: List[str] = Field(description="List of AtomicFact IDs to be used")
    
    # Connection (Crit 3 - Flow)
    transition_in: Optional[str] = Field(description="suggested transition phrase from previous paragraph")
