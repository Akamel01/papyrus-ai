"""
Sidebar Component.

Renders the configuration sidebar with Golden Theme and Custom Layouts.
Uses "Header + Collapsed Widget + Footer" pattern for strict mockup adherence.
"""

import streamlit as st

from app.components.theme import GOLD, TEXT_GREY, MUTED_TEXT
from app.components.sidebar_styles import SIDEBAR_CSS, LET_AI_DECIDE_CSS, get_disabled_slider_css
from app.components.sidebar_config import SidebarConfig
from app.components.quick_upload import render_quick_upload
from app.auth_helper import get_current_user, logout


def render_custom_header(title: str, value: str = "", active: bool = False):
    """Renders a custom header row with Title (Left) and Value (Right)."""
    value_html = f'<span style="color: {GOLD}; font-family: monospace;">{value}</span>' if value else ""
    st.markdown(f'''<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;"><span style="color: {TEXT_GREY}; font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">{title}</span>{value_html}</div>''', unsafe_allow_html=True)


def render_custom_footer(options: list, selected_index: int, uppercase: bool = False):
    """Renders option labels below a slider with the selected option highlighted in gold.
    
    Args:
        options: List of option labels (e.g., ["Low", "Medium", "High"])
        selected_index: Index of the currently selected option
        uppercase: If True, convert labels to uppercase
    """
    labels_html = ""
    for i, opt in enumerate(options):
        label = opt.upper() if uppercase else opt
        align = "left" if i == 0 else ("center" if i == 1 else "right")
        color = GOLD if i == selected_index else MUTED_TEXT
        labels_html += f'<div style="text-align: {align}; flex: 1; color: {color}; font-size: 12px; font-weight: 500;">{label}</div>'
    
    st.markdown(f'''<div style="display: flex; justify-content: space-between; margin-top: -20px; margin-bottom: 8px;">{labels_html}</div>''', unsafe_allow_html=True)


def render_divider():
    """Renders a horizontal divider line."""
    st.markdown('<div style="height: 1px; background-color: rgba(255,255,255,0.1); margin: 16px 0;"></div>', unsafe_allow_html=True)


def render_sidebar() -> SidebarConfig:
    """Render the sidebar and return configuration settings.
    
    Returns:
        SidebarConfig dataclass with all sidebar settings.
    """
    # Initialize return variables to safe defaults
    depth_level = "High"
    selected_model = "gpt-oss:120b-cloud"
    paper_range = (40, 60)
    auto_decide_papers = True
    enable_sequential = True
    enable_section_mode = True
    enable_clarification = False
    show_sources = True
    show_confidence = True
    citation_density = "High"
    auto_citation_density = True

    with st.sidebar:
        # === USER INFO SECTION ===
        user = get_current_user()
        if user:
            col1, col2 = st.columns([3, 1])
            with col1:
                display_name = user.display_name or user.email.split('@')[0]
                st.markdown(f'''
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                    <div style="width: 28px; height: 28px; background: linear-gradient(135deg, {GOLD}, #d97706);
                                border-radius: 50%; display: flex; align-items: center; justify-content: center;
                                font-size: 12px; font-weight: bold; color: black;">
                        {display_name[0].upper()}
                    </div>
                    <span style="color: {TEXT_GREY}; font-size: 13px; font-weight: 500;">{display_name}</span>
                </div>
                ''', unsafe_allow_html=True)
            with col2:
                if st.button("", key="logout_btn", help="Sign out"):
                    logout()
                    st.rerun()
                # Style the logout button as icon
                st.markdown('''
                <style>
                    [data-testid="stSidebar"] button[kind="secondary"][data-testid="stButton"]:has([aria-label="Sign out"]) {
                        background: transparent !important;
                        border: none !important;
                        padding: 4px !important;
                    }
                </style>
                ''', unsafe_allow_html=True)

            # Settings link
            st.markdown(f'''
            <a href="/settings" target="_self" style="color: {MUTED_TEXT}; font-size: 11px; text-decoration: none; display: block; margin-bottom: 12px;">
                Settings
            </a>
            ''', unsafe_allow_html=True)

            render_divider()

        # === QUICK UPLOAD SECTION ===
        render_quick_upload()
        render_divider()

        # === KNOWLEDGE BASE SECTION ===
        st.markdown(f'<div style="color: {TEXT_GREY}; font-weight: 900; font-size: 12px; letter-spacing: 0.05em; margin-bottom: 8px;">KNOWLEDGE BASE</div>', unsafe_allow_html=True)

        knowledge_source_options = {
            "both": "Both (My Docs + Shared KB)",
            "shared_only": "Shared KB Only",
            "user_only": "My Documents Only"
        }

        knowledge_source = st.radio(
            "Search scope",
            options=list(knowledge_source_options.keys()),
            format_func=lambda x: knowledge_source_options[x],
            index=0,
            key="knowledge_source",
            label_visibility="collapsed"
        )

        # Show Quick Upload count if any
        quick_upload_count = len(st.session_state.get("quick_uploads", []))
        if quick_upload_count > 0:
            st.caption(f"+ {quick_upload_count} Quick Upload(s) always included")

        render_divider()

        # === 1. RESEARCH CONTEXT ===
        # Inject CSS and Header together to avoid extra spacing/container overhead
        st.markdown(SIDEBAR_CSS + f'<div style="color: {TEXT_GREY}; font-weight: 900; font-size: 14px; letter-spacing: 0.05em; margin-bottom: 8px;">RESEARCH CONTEXT</div>', unsafe_allow_html=True)
        
        # Investigation Depth
        render_custom_header("Investigation Depth")
        
        depth_opts = ["Low", "Medium", "High"]
        selected_depth_str = st.select_slider(
            "Investigation Depth",
            options=depth_opts,
            value="High",
            label_visibility="collapsed"
        )
        depth_index = depth_opts.index(selected_depth_str)
        depth_level = selected_depth_str
        
        render_custom_footer(depth_opts, depth_index)
        
        render_divider()
        
        # === 2. SOURCE SCOPE ===
        st.markdown(f'<div style="color: {TEXT_GREY}; font-weight: 900; font-size: 12px; letter-spacing: 0.05em; margin-bottom: 8px;">SOURCE SCOPE</div>', unsafe_allow_html=True)
        
        # Let AI Decide - checkbox to LEFT of text on same line
        auto_mode = st.checkbox("Let AI Decide", value=False, key="auto_decide_checkbox")
        
        auto_decide_papers = auto_mode
        auto_citation_density = auto_mode 

        # Target Sources
        if "target_sources" not in st.session_state:
            st.session_state.target_sources = (40, 60)
         
        # Header (Tooltips enforced by CSS)
        render_custom_header("Target Sources", "", active=True)
        
        if auto_mode:
            st.markdown(get_disabled_slider_css("Target Sources"), unsafe_allow_html=True)
            
        paper_range = st.slider(
            "Target Sources",
            min_value=5,
            max_value=100,
            key="target_sources",
            label_visibility="collapsed",
            disabled=auto_mode
        )
        
        st.markdown('<div style="margin-bottom: 12px;"></div>', unsafe_allow_html=True)

        # Citation Density
        if "citation_density" not in st.session_state:
            st.session_state.citation_density = "High"
            
        render_custom_header("Citation Density", "", active=True)
        
        if auto_mode:
            st.markdown(get_disabled_slider_css("Citation Density"), unsafe_allow_html=True)

        density_opts = ["Low", "Medium", "High"]
        citation_density = st.select_slider(
            "Citation Density",
            options=density_opts,
            key="citation_density",
            label_visibility="collapsed",
            disabled=auto_mode
        )
        
        density_idx = density_opts.index(citation_density)
        render_custom_footer(density_opts, density_idx, uppercase=True)
        
        render_divider()
        
        # === 3. NEURAL FEATURES ===
        st.markdown(f'<div style="color: {TEXT_GREY}; font-weight: 900; font-size: 12px; letter-spacing: 0.05em; margin-bottom: 8px;">NEURAL FEATURES</div>', unsafe_allow_html=True)
        
        enable_sequential = st.checkbox("Sequential Thinking", value=True)
        
        section_disabled = not enable_sequential
        enable_section_mode = st.checkbox(
            "Section Mode", 
            value=False, 
            disabled=section_disabled
        )
        if section_disabled: 
            enable_section_mode = False
            
        enable_clarification = st.checkbox("Clarification Questions", value=False)
        
        st.markdown('<div style="margin-bottom: 12px;"></div>', unsafe_allow_html=True)
        
        # Inference Model
        render_custom_header("Inference Model")
        model_options = [
            "gpt-oss:120b-cloud",
            "deepseek-v3.1:671b-cloud", 
            "kimi-k2-thinking:cloud",
            "minimax-m2:cloud",
            "glm-4.6:cloud",
            "gpt-oss:20b-cloud",
            "gemma:7b",   
            "gpt-oss:20b",
            "gemma3:27b",
            "gpt-oss:120b"
        ]
        selected_model = st.selectbox(
            "Inference Model",
            options=model_options,
            index=0,
            label_visibility="collapsed"
        )
        
        # Footer version
        st.markdown(f"""
            <div style="margin-top: 16px; text-align: center; color: {TEXT_GREY}; opacity: 0.4; font-family: monospace; font-size: 10px;">
                v2.4.0-stable
            </div>
        """, unsafe_allow_html=True)
        
        # No spacer needed

        
        # Reset Button - simple centered, single line
        st.markdown('''
            <style>
            [data-testid="stSidebar"] [data-testid="stButton"] {
                display: flex;
                justify-content: center;
                width: 100%;
            }
            [data-testid="stSidebar"] [data-testid="stButton"] button {
                white-space: nowrap;
                width: 100%;
            }
            </style>
        ''', unsafe_allow_html=True)
        if st.button("Reset Session", type="secondary"):
            st.session_state.messages = []
            st.session_state.is_processing = False
            st.rerun()

    return SidebarConfig(
        depth_level=depth_level,
        selected_model=selected_model,
        paper_range=paper_range,
        auto_decide_papers=auto_decide_papers,
        enable_sequential=enable_sequential,
        enable_section_mode=enable_section_mode,
        enable_clarification=enable_clarification,
        show_sources=show_sources,
        show_confidence=show_confidence,
        citation_density=citation_density,
        auto_citation_density=auto_citation_density,
        knowledge_source=knowledge_source
    )
