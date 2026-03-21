"""
Style Injection Module.

Loads and injects CSS from external files for better maintainability.
"""

import streamlit as st
from pathlib import Path


def inject_theme_css():
    """Inject the main theme CSS from external file."""
    css_path = Path(__file__).parent / "theme.css"
    
    if css_path.exists():
        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()
        st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)
    else:
        # Fallback: log warning but don't break the app
        st.warning(f"Theme CSS not found at {css_path}")


def inject_monitor_css():
    """Inject the monitor panel CSS from external file."""
    css_path = Path(__file__).parent / "monitor.css"
    
    if css_path.exists():
        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()
        st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)


def inject_processing_overlay():
    """Inject sidebar overlay for processing state."""
    st.markdown("""
    <script>
    if (!document.getElementById('sidebar-overlay')) {
        const overlay = document.createElement('div');
        overlay.id = 'sidebar-overlay';
        overlay.className = 'sidebar-overlay';
        overlay.innerHTML = `<div class="sidebar-overlay-text">⏳ Query in Progress...</div><div class="sidebar-overlay-subtext">Click STOP to cancel</div>`;
        document.body.appendChild(overlay);
    }
    </script>
    """, unsafe_allow_html=True)


def remove_processing_overlay():
    """Remove sidebar overlay after processing."""
    st.markdown("""
    <script>
    const overlay = document.getElementById('sidebar-overlay');
    if (overlay) overlay.remove();
    </script>
    """, unsafe_allow_html=True)

