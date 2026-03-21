"""
Sidebar Configuration Dataclass.

Structured return type for render_sidebar() function.
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass
class SidebarConfig:
    """Configuration returned by the sidebar component."""
    
    depth_level: str
    """Investigation depth level ("Low", "Medium", "High")."""
    
    selected_model: str
    """Selected LLM model name."""
    
    paper_range: Tuple[int, int]
    """Min and max papers to retrieve (e.g., (40, 60))."""
    
    auto_decide_papers: bool
    """If True, AI decides paper range based on query complexity."""
    
    enable_sequential: bool
    """Enable sequential thinking mode."""
    
    enable_section_mode: bool
    """Enable section-by-section generation (requires sequential)."""
    
    enable_clarification: bool
    """Enable clarification questions before processing."""
    
    show_sources: bool
    """Show source excerpts in response."""
    
    show_confidence: bool
    """Show confidence badge in response."""
    
    citation_density: str
    """Citation density level ("Low", "Medium", "High")."""
    
    auto_citation_density: bool
    """If True, AI decides citation density based on query."""
