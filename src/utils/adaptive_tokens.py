"""
Adaptive Token Manager for RAG Pipeline.

This module provides a unified system for calculating token limits across all
components of the RAG pipeline (Search, Generation, Proofreading, Planning).
It replaces hardcoded limits with dynamic calculations based on:
1. Research Depth (Low/Medium/High)
2. Content Size (number of citations, sections)
3. Task Type (Generation vs Editing)
"""

import math
from typing import Dict, Any, Optional


class AdaptiveTokenManager:
    """
    Unified token limit calculator for all RAG components.
    
    Principles:
    - Input/Output Ratio: Ensure context is sufficient for expected output (target 3:1)
    - Proportionality: Limits scale with content size (citations, sections)
    - Depth Awareness: Higher depths get higher multipliers
    - Task Specificity: Different ratios for generation vs editing
    """
    
    # Configuration Constants
    DEPTH_MULTIPLIERS = {
        "Low": 1.0, 
        "Medium": 1.3, 
        "High": 1.6,
        "Deep": 2.0  # Future proofing
    }
    
    # Ratios
    CHARS_PER_TOKEN = 4.0     # Conservative estimate
    TOKENS_PER_CHUNK = 800    # Average tokens per retrieved chunk
    
    # Base Limits
    BASE_SECTION_OUTPUT = 1500  # Minimum tokens for a section
    
    # Depth-based rerank counts (must match depth_presets.py top_k_rerank)
    RERANK_COUNTS = {"Low": 20, "Medium": 40, "High": 75}
    
    def __init__(self, depth: str = "Medium", orchestration: Dict = None):
        """
        Initialize the manager for a specific query execution.
        
        Args:
            depth: Research depth ("Low", "Medium", "High")
            orchestration: Orchestration plan containing section details
        """
        self.depth = depth
        self.mult = self.DEPTH_MULTIPLIERS.get(depth, 1.3)
        
        # Parse orchestration data
        self.orchestration = orchestration or {"sections": []}
        self.sections = self.orchestration.get("sections", [])
        self.num_sections = len(self.sections)
        self.total_citations = sum(s.get("citations", 0) for s in self.sections)
        
        # If no orchestration provided (e.g. early stage), use reasonable defaults
        if not self.sections:
            self.num_sections = {"Low": 3, "Medium": 5, "High": 7}[depth]
            self.total_citations = {"Low": 10, "Medium": 30, "High": 60}[depth]

    def get_section_limits(self, section_index: int, section_citations: int) -> Dict[str, int]:
        """
        Calculate context and output limits for a specific section.
        
        Context sizing is DECOUPLED from output sizing:
        - Context is sized to fit ALL reranked chunks (top_k_rerank × TOKENS_PER_CHUNK)
        - Output is sized based on citation density and depth
        
        Args:
            section_index: Index of the section (0-based)
            section_citations: Expected number of citations for this section
            
        Returns:
            Dict containing max_output_tokens, max_context_tokens, max_context_chars
        """
        # 1. Output Calculation (unchanged — sized for expected prose length)
        citation_factor = max(0.8, min(2.5, section_citations / 10))
        output_tokens = int(self.BASE_SECTION_OUTPUT * self.mult * citation_factor)
        
        # Ensure High depth gets at least 2000 tokens per section if citations are high
        if self.depth == "High" and section_citations >= 15:
            output_tokens = max(output_tokens, 2400)
            
        # 2. Context Calculation — DECOUPLED from output
        # Context MUST fit all reranked chunks for this depth level
        # Formula: top_k_rerank × TOKENS_PER_CHUNK
        rerank_count = self.RERANK_COUNTS.get(self.depth, 40)
        input_tokens = rerank_count * self.TOKENS_PER_CHUNK  # e.g., High: 75 × 800 = 60,000
        
        return {
            "max_output_tokens": output_tokens,
            "max_context_tokens": input_tokens,
            "max_context_chars": int(input_tokens * self.CHARS_PER_TOKEN),
            "expected_papers": int(input_tokens * self.CHARS_PER_TOKEN / 3000)
        }

    def get_proofreading_limits(self, pass_id: str, input_tokens: int) -> int:
        """
        Calculate output limits for proofreading passes.
        
        Args:
            pass_id: Identifier for the pass ("pass1", "pass2", etc.)
            input_tokens: Estimated token count of input text
            
        Returns:
            Max output tokens
        """
        # Safety margin to prevent truncation
        min_limit = 500
        
        if pass_id == "pass1_micro":
            # Cleaning pass: Input ≈ Output. Allow small expansion.
            return max(min_limit, int(input_tokens * 1.2))
            
        elif pass_id == "pass2_review":
            # Instruction generation: List of edits. Much smaller than input.
            # Allocating 200 tokens per section for instructions
            return max(min_limit, self.num_sections * 300)
            
        elif pass_id == "pass3a_structural":
            # Applying edits: Content might expand significantly if clarifications added
            return max(min_limit, int(input_tokens * 1.6))
            
        elif pass_id == "pass3b_flow":
            # Flow enhancement: Content should be preserved
            return max(min_limit, int(input_tokens * 1.4))
            
        elif pass_id == "final_polish":
            return max(min_limit, int(input_tokens * 1.2))
            
        return 2000  # Default fallback

    def get_planning_limits(self) -> Dict[str, int]:
        """Calculate limits for planning phase tasks."""
        return {
            "knowledge_map": 500 + int(self.total_citations * 10),
            "orchestration": max(1000, self.num_sections * 300),
            "outline": max(500, self.num_sections * 100)
        }

    def get_utility_limits(self, task: str) -> int:
        """Calculate limits for utility tasks."""
        limits = {
            "query_expansion": 120,   # Short queries
            "hyde": 250,              # One hypothetical paragraph
            "reflection": 150,        # Short decision + reasoning
            "audit": 1200,            # Detailed coverage analysis
            "gap_analysis": 600,      # Gap identification
            "clarification": 500,     # Clarification questions
            "section_completion": 500 # Completing truncated sections
        }
        return limits.get(task, 500)
