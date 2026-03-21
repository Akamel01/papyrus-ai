"""
Components Package.

UI components extracted from main.py for modularity and maintainability.
"""

from app.components.sidebar import render_sidebar
from app.components.sidebar_config import SidebarConfig
from app.components.progress_display import (
    render_status_block,
    render_progress_steps,
    render_progress_block,
    SVG_ICONS
)
from app.components.welcome_screen import (
    render_welcome_screen,
    get_welcome_screen_html
)

__all__ = [
    "render_sidebar",
    "SidebarConfig",
    "render_status_block",
    "render_progress_steps",
    "render_progress_block",
    "render_welcome_screen",
    "get_welcome_screen_html",
    "SVG_ICONS",
]

