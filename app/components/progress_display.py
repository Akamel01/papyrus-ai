"""
Progress Display Components.

Renders progress indicators, status blocks, and step pills.
"""

import streamlit as st
from typing import List, Optional


# SVG Icons for status blocks
SVG_ICONS = {
    "analyze": '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>',
    "search": '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>',
    "rerank": '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"></path></svg>',
    "generate": '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>',
    "validate": '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>',
    "brain": '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/></svg>',
}


def render_status_block(
    icon: str, 
    title: str, 
    subtitle: str, 
    state: str = "active"
) -> str:
    """
    Render a Glassmorphism Status Block.
    
    Args:
        icon: SVG content or key from SVG_ICONS
        title: Main status text (e.g., "Sequential Thinking")
        subtitle: Secondary text (e.g., "Step 2/5 • Reasoning")
        state: "active" or "completed"
        
    Returns:
        HTML string for the status block
    """
    # Get SVG from dictionary if it's a key
    icon_svg = SVG_ICONS.get(icon, icon)
    
    active_class = "active" if state == "active" else ""
    
    return f'''<div class="status-block {active_class}"><div class="status-icon">{icon_svg}</div><div class="status-content"><div class="status-title">{title}</div><div class="status-subtitle">{subtitle}</div></div></div>'''


def render_progress_steps(
    current_step: int, 
    steps: Optional[List[str]] = None, 
    detail: str = ""
) -> str:
    """
    Render progress indicator showing query processing steps as pills.
    
    Args:
        current_step: Index of current step (0-based)
        steps: List of step names
        detail: Current step detail text
        
    Returns:
        HTML string for the progress pills
    """
    if steps is None:
        steps = ["Expanding", "Searching", "Reranking", "Generating", "Validating"]
    
    pills_html = ""
    for i, step in enumerate(steps):
        if i < current_step:
            # Completed
            pill_class = "background:#10b981;color:white;"
            icon = "✓"
        elif i == current_step:
            # Active
            pill_class = "background:#f59e0b;color:black;animation:pulse-gold 2s infinite;"
            icon = "●"
        else:
            # Pending
            pill_class = "background:#262626;color:#6b7280;"
            icon = "○"
        
        pills_html += f'''<div style="display:flex;align-items:center;gap:6px;padding:6px 12px;border-radius:9999px;font-size:12px;font-family:'JetBrains Mono',monospace;{pill_class}"><span>{icon}</span><span>{step}</span></div>'''
    
    return f'''<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">{pills_html}</div>{f'<div style="color:#6b7280;font-size:11px;font-style:italic;">{detail}</div>' if detail else ''}'''


def render_progress_block(
    step_num: int,
    total_steps: int,
    step_name: str,
    sub_step: str = "",
    show_icon: bool = True
) -> str:
    """
    Render a progress status block for the center window during processing.
    
    Args:
        step_num: Current step number (1-based)
        total_steps: Total number of steps
        step_name: Name of the current main step
        sub_step: Description of current sub-step
        show_icon: Whether to show the brain icon
        
    Returns:
        HTML string for the progress block
    """
    icon_html = ""
    if show_icon:
        icon_html = f'''
        <svg class="animate-pulse" style="color:#fbbf24;filter:drop-shadow(0 0 4px #f59e0b);" 
             width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/>
            <path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/>
        </svg>
        '''
    
    return f'''<div style="background:rgba(23,23,23,0.5);border-left:2px solid rgba(245,158,11,0.5);padding:8px 16px;margin-bottom:16px;border-radius:0 6px 6px 0;"><div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">{icon_html}<span style="font-size:12px;font-family:'JetBrains Mono',monospace;color:#f59e0b;">{step_name} • Step {step_num}/{total_steps}</span></div>{f'<p style="font-size:11px;color:#6b7280;font-style:italic;margin:0;">{sub_step}</p>' if sub_step else ''}</div>'''
