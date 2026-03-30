"""
Sidebar Styles Module.

Contains all CSS styles for the sidebar component using theme constants.
"""

from app.components.theme import (
    GOLD, GOLD_GLOW, BLACK, DARK_GREY, BORDER_GREY,
    TEXT_GREY, LIGHT_TEXT, MUTED_TEXT
)

SIDEBAR_CSS = f"""
<style>
:root {{
    --primary-color: {GOLD} !important;
}}

/* Global Sidebar */
[data-testid="stSidebar"] {{
    background-color: {BLACK} !important;
    border-right: 1px solid {BORDER_GREY} !important;
}}
[data-testid="stSidebar"] > div:first-child,
[data-testid="stSidebarContent"],
[data-testid="stSidebarUserContent"] {{
    padding-top: 0px !important;
    padding-left: 24px !important;
    padding-right: 24px !important;
    padding-bottom: 20px !important; /* Add bottom padding */
    display: flex !important;
    flex-direction: column !important;
    height: 100vh !important;
    justify-content: flex-start !important; /* Stack content at top */
    gap: 0px !important;
}}
/* Ensure all content groups except the last one take natural height */
[data-testid="stSidebar"] > div:first-child > div:not(:last-child) {{
    flex: 0 1 auto !important;
}}
/* Force the last generic container (which holds our button) to bottom */
[data-testid="stSidebar"] > div:first-child > div:last-child {{
    margin-top: auto !important;
    padding-bottom: 0 !important;
}}
/* Hide close button area and push content up */
[data-testid="stSidebar"] [data-testid="stSidebarCloseButton"] {{
    display: none !important;
}}
[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {{
    display: none !important;
}}
/* Remove bottom margins from last button */
[data-testid="stSidebar"] .stButton {{
    padding-bottom: 0px !important;
    margin-bottom: 0px !important;
}}

/* === SLIDER LOGIC (Targeting Gold) === */

/* 1. KNOBS: Always Gold */
[data-testid="stSidebar"] [role="slider"] {{
    background-color: {GOLD} !important;
    border: 2px solid {GOLD} !important;
    box-shadow: 0 0 10px {GOLD_GLOW} !important;
}}

/* 2. INACTIVE TRACK (The Rail): Always Dark Grey */
[data-testid="stSidebar"] div[data-baseweb="slider"] > div > div:first-child {{
    background-color: {DARK_GREY} !important;
}}
/* Note: Slider click area is controlled by Streamlit internally - can't be extended via CSS */

/* 3. ACTIVE TRACK OVERRIDES (Force NO COLOR / Dark Grey) */
/* User Request: "no colors at all... only the knobs can remain colored" */
/* We force the active track to match the inactive rail (#333333) */

[data-testid="stSidebar"] div[data-baseweb="slider"] div[style*="background"]:not([role="slider"]),
[data-testid="stSidebar"] div[data-baseweb="slider"] div[style*="255"]:not([role="slider"]),
[data-testid="stSidebar"] div[data-baseweb="slider"] div[style*="rgb"]:not([role="slider"]) {{
     background-color: {DARK_GREY} !important;
}}

/* 4. CLEANUP: Hide Ticks and Min/Max Labels (Global) */
/* This removes the "5" and "100" under Target Sources, and "Low"/"High" under others if natively rendered */
[data-testid="stTickBar"],
[data-testid="stSliderTickBar"],
[data-testid="stTickBarMinMax"],
[data-testid="stSidebar"] div[data-testid="stTickBarMinMax"],
/* Hide ALL slider value text displays (grey text like "100", "High") */
[data-testid="stSidebar"] [data-testid="stSliderTickBarMax"],
[data-testid="stSidebar"] [data-testid="stSliderTickBarMin"],
[data-testid="stSidebar"] .stSlider [data-baseweb="slider"] + div,
[data-testid="stSidebar"] div[data-baseweb="slider"] ~ div[style*="color"],
[data-testid="stSidebar"] div[data-baseweb="slider"] ~ div:not([data-testid]):not([data-baseweb]) {{
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
    height: 0 !important;
    width: 0 !important;
}}

/* Hide ALL slider hover tooltips for ALL sliders (single and range) */
[data-testid="stSidebar"] div[data-baseweb="slider"] div[role="tooltip"] {{
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
}}

/* Hide thumb value text for single-value sliders ONLY */
[data-testid="stSidebar"] div[data-baseweb="slider"]:not(:has([role="slider"] ~ [role="slider"])) div[data-testid="stSliderThumbValue"] {{
    display: none !important;
}}

/* Show grey text over Target Sources range slider knobs */
[data-testid="stSidebar"] div[data-baseweb="slider"]:has([role="slider"] ~ [role="slider"]) div[data-testid="stSliderThumbValue"] {{
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    color: {TEXT_GREY} !important;
}}

/* NUCLEAR: Hide ALL thumb value displays for single-value sliders */
/* Target Investigation Depth and Citation Density specifically by aria-label */
[data-testid="stSidebar"] [aria-label="Investigation Depth"] div[data-baseweb="popover"],
[data-testid="stSidebar"] [aria-label="Investigation Depth"] [role="tooltip"],
[data-testid="stSidebar"] [aria-label="Investigation Depth"] div[class*="ThumbValue"],
[data-testid="stSidebar"] [aria-label="Investigation Depth"] div[style*="position: absolute"]:not([role="slider"]),
[data-testid="stSidebar"] [aria-label="Citation Density"] div[data-baseweb="popover"],
[data-testid="stSidebar"] [aria-label="Citation Density"] [role="tooltip"],
[data-testid="stSidebar"] [aria-label="Citation Density"] div[class*="ThumbValue"],
[data-testid="stSidebar"] [aria-label="Citation Density"] div[style*="position: absolute"]:not([role="slider"]) {{
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
    height: 0 !important;
    width: 0 !important;
}}

/* Hide value labels on knobs - ONLY for single-value sliders */
[data-testid="stSidebar"] div[data-baseweb="slider"]:not(:has([role="slider"] ~ [role="slider"])) div[data-baseweb="popover"],
[data-testid="stSidebar"] div[data-baseweb="slider"]:not(:has([role="slider"] ~ [role="slider"])) div[class*="Label"],
[data-testid="stSidebar"] div[data-baseweb="slider"]:not(:has([role="slider"] ~ [role="slider"])) div[class*="Thumb"],
[data-testid="stSidebar"] div[data-baseweb="slider"]:not(:has([role="slider"] ~ [role="slider"])) div[class*="Value"],
[data-testid="stSidebar"] div[data-baseweb="slider"]:not(:has([role="slider"] ~ [role="slider"])) [role="slider"] + div,
[data-testid="stSidebar"] div[data-baseweb="slider"]:not(:has([role="slider"] ~ [role="slider"])) div[style*="position: absolute"] > div {{
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
    color: transparent !important;
    pointer-events: none !important;
    height: 0 !important;
    overflow: hidden !important;
}}

/* Style value labels on Target Sources range slider (keep visible, style as orange) */
[data-testid="stSidebar"] div[data-baseweb="slider"]:has([role="slider"] ~ [role="slider"]) div[data-baseweb="popover"],
[data-testid="stSidebar"] div[data-baseweb="slider"]:has([role="slider"] ~ [role="slider"]) div[class*="Label"] {{
    visibility: visible !important;
    opacity: 1 !important;
    color: {GOLD} !important;
}}

/* === SELECTBOX (Dropdown) === */
[data-testid="stSidebar"] [data-baseweb="select"] > div {{
    background-color: transparent !important;
    border-color: {BORDER_GREY} !important;
    color: {LIGHT_TEXT} !important;
}}
[data-testid="stSidebar"] [data-baseweb="select"]:hover > div {{
    border-color: {GOLD} !important;
}}
[data-testid="stSidebar"] [data-baseweb="select"] div[class*="Value"] {{
    color: {LIGHT_TEXT} !important;
}}
[data-testid="stSidebar"] [data-baseweb="select"] svg {{
    fill: {TEXT_GREY} !important;
}}

/* === CHECKBOXES (Fix: Remove Text Highlight) === */
/* 1. Force transparent background on container and label */
[data-testid="stSidebar"] [data-baseweb="checkbox"] {{
    background-color: transparent !important;
}}
[data-testid="stSidebar"] [data-baseweb="checkbox"] label {{
    background-color: transparent !important;
}}

/* 2. Target the Text P element specifically */
[data-testid="stSidebar"] [data-baseweb="checkbox"] p {{
    background-color: transparent !important;
    color: {LIGHT_TEXT} !important;
}}

/* 3. The Checkbox Box itself */
/* Use accent-color on the input for the checkmark */
[data-testid="stSidebar"] [data-baseweb="checkbox"] input {{
    accent-color: {GOLD} !important;
}}

/* === DISABLED STATE (Dimming) === */
[data-testid="stSidebar"] [data-baseweb="checkbox"]:has(input:disabled) {{
     opacity: 0.4 !important;
     cursor: not-allowed !important;
}}
[data-testid="stSidebar"] [data-baseweb="checkbox"]:has(input:disabled) p,
[data-testid="stSidebar"] [data-baseweb="checkbox"]:has(input:disabled) div {{
     color: {TEXT_GREY} !important; 
}}

/* Remove margins */
[data-testid="stSidebar"] .stElementContainer {{
    margin-bottom: 0px !important;
    margin-top: 0px !important;
}}

/* ===== HIDE DEFAULT STREAMLIT NAVIGATION ===== */
/* We'll use custom navigation at bottom of sidebar instead */
[data-testid="stSidebarNav"] {{
    display: none !important;
}}

/* ===== FILE UPLOADER DARK THEME ===== */
/* Fix white background on upload box */
[data-testid="stSidebar"] [data-testid="stFileUploader"] {{
    background-color: #1a1a1a !important;
}}

[data-testid="stSidebar"] [data-testid="stFileUploader"] section,
[data-testid="stSidebar"] [data-testid="stFileUploadDropzone"] {{
    background-color: #1a1a1a !important;
    border: 1px dashed #404040 !important;
    border-radius: 8px !important;
    padding: 16px !important;
}}

[data-testid="stSidebar"] [data-testid="stFileUploader"] section > div,
[data-testid="stSidebar"] [data-testid="stFileUploadDropzone"] > div {{
    background-color: transparent !important;
}}

/* File uploader text */
[data-testid="stSidebar"] [data-testid="stFileUploader"] small {{
    color: {MUTED_TEXT} !important;
}}

[data-testid="stSidebar"] [data-testid="stFileUploader"] span {{
    color: {TEXT_GREY} !important;
}}

/* Browse files button - proper sizing */
[data-testid="stSidebar"] [data-testid="stFileUploader"] button,
[data-testid="stSidebar"] [data-testid="stFileUploader"] [data-testid="stBaseButton-secondary"],
[data-testid="stSidebar"] [data-testid="stFileUploader"] [data-testid="baseButton-secondary"] {{
    background-color: #262626 !important;
    color: {TEXT_GREY} !important;
    border: 1px solid #404040 !important;
    border-radius: 6px !important;
    padding: 8px 16px !important;
    width: 100% !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    transition: all 0.15s ease !important;
}}

[data-testid="stSidebar"] [data-testid="stFileUploader"] button:hover {{
    border-color: {GOLD} !important;
    color: {GOLD} !important;
    background-color: rgba(255, 165, 0, 0.08) !important;
}}

/* File uploader drag area text styling */
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"],
[data-testid="stSidebar"] [data-testid="stFileUploadDropzone"] {{
    background-color: #1a1a1a !important;
    border-color: #404040 !important;
}}

[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] > div,
[data-testid="stSidebar"] [data-testid="stFileUploadDropzone"] > div {{
    color: {TEXT_GREY} !important;
}}
</style>
"""

# CSS for positioning the "Let AI Decide" checkbox on the right
LET_AI_DECIDE_CSS = """
<style>
[data-testid="stSidebar"] .stElementContainer:has([data-testid="stCheckbox"][aria-label="Let AI Decide"]) {
    position: relative;
    margin-top: -38px !important;
    display: flex;
    justify-content: flex-end;
}
</style>
"""

def get_disabled_slider_css(label: str) -> str:
    """Generate CSS to disable a specific slider by label."""
    return f'<style>[data-testid="stSidebar"] .stElementContainer:has([aria-label="{label}"]) {{ opacity: 0.4; pointer-events: none; }}</style>'
