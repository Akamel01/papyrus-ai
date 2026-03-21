"""
Welcome Screen Component.

Renders the home state with title, feature cards, and centered search input.
"""

import streamlit as st


# TYPOGRAPHY CONFIGURATION (User Adjustable)
CARD_TITLE_SIZE = "16px"
CARD_DESC_SIZE = "14px"

def get_indexed_papers_count() -> str:
    """Fetch exact embedded paper count from SQLite, fallback to 52,000+."""
    import sqlite3
    import os
    db_path = "data/sme.db"
    if not os.path.exists(db_path):
        return "52,000+"
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM papers WHERE status='embedded'")
            count = cursor.fetchone()[0]
            return f"{count:,}"
    except Exception:
        return "52,000+"



def render_welcome_screen() -> None:
    """
    Render the welcome screen for the home state (State A).
    
    This displays:
    - Title badge with paper count
    - Main title and subtitle
    - Three feature cards (Deep Research, Chain of Thought, Real-time RAG)
    """
    papers_count = get_indexed_papers_count()
    
    # Welcome HTML - MUST be flush left to prevent Streamlit treating as code block
    welcome_html = f"""<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:60vh;text-align:center;">
<div style="margin-bottom:40px;">
<div style="display:inline-block;padding:4px 12px;margin-bottom:16px;border:1px solid rgba(245,158,11,0.3);border-radius:9999px;background:rgba(120,53,15,0.1);backdrop-filter:blur(4px);margin-top:16px;">
<span style="font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;color:#f59e0b;letter-spacing:0.05em;">{papers_count} INDEXED PAPERS</span>
</div>
<h1 style="color:#ffffff;font-family:'Merriweather',serif;font-size:3rem;margin-bottom:8px;font-weight:700;letter-spacing:-0.02em;">AI Synthesis Engine</h1>
<p style="font-family:'Inter',sans-serif;font-size:14px;color:#6b7280;font-weight:300;max-width:600px;margin:0 auto;">Deep academic analysis powered by neural retrieval.</p>
</div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:32px;width:100%;max-width:48rem;">

<div class="glass-card" style="padding:16px;border-radius:12px;display:flex;flex-direction:column;align-items:center;text-align:center;">
<div style="width:40px;height:40px;margin-bottom:12px;border-radius:9999px;background:#262626;display:flex;align-items:center;justify-content:center;color:#9ca3af;">
<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/></svg>
</div>
<div style="color:#e5e7eb;font-size:{CARD_TITLE_SIZE};font-weight:600;margin-bottom:4px;">Deep Research</div>
<p style="color:#6b7280;font-size:{CARD_DESC_SIZE};line-height:1.25;">Multi-hop traversal of citation networks.</p>
</div>
<div class="glass-card" style="padding:16px;border-radius:12px;display:flex;flex-direction:column;align-items:center;text-align:center;">
<div style="width:40px;height:40px;margin-bottom:12px;border-radius:9999px;background:#262626;display:flex;align-items:center;justify-content:center;color:#9ca3af;">
<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/></svg>
</div>
<div style="color:#e5e7eb;font-size:{CARD_TITLE_SIZE};font-weight:600;margin-bottom:4px;">Chain of Thought</div>
<p style="color:#6b7280;font-size:{CARD_DESC_SIZE};line-height:1.25;">Self-correcting logical reasoning paths.</p>
</div>
<div class="glass-card" style="padding:16px;border-radius:12px;display:flex;flex-direction:column;align-items:center;text-align:center;">
<div style="width:40px;height:40px;margin-bottom:12px;border-radius:9999px;background:#262626;display:flex;align-items:center;justify-content:center;color:#9ca3af;">
<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/></svg>
</div>
<div style="color:#e5e7eb;font-size:{CARD_TITLE_SIZE};font-weight:600;margin-bottom:4px;">Real-time RAG</div>
<p style="color:#6b7280;font-size:{CARD_DESC_SIZE};line-height:1.25;">Live vector search with millisecond latency.</p>
</div>
</div>
</div>"""
    
    st.markdown(welcome_html, unsafe_allow_html=True)


def get_welcome_screen_html() -> str:
    """
    Get the welcome screen HTML string for use in other contexts.
    
    Returns:
        HTML string for the welcome screen
    """
    papers_count = get_indexed_papers_count()
    
    return f"""<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:60vh;text-align:center;">
<div style="margin-bottom:40px;">
<div style="display:inline-block;padding:4px 12px;margin-bottom:16px;border:1px solid rgba(245,158,11,0.3);border-radius:9999px;background:rgba(120,53,15,0.1);backdrop-filter:blur(4px);margin-top:16px;">
<span style="font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;color:#f59e0b;letter-spacing:0.05em;">● {papers_count} INDEXED PAPERS</span>
</div>
<h1 style="color:#ffffff;font-family:'Merriweather',serif;font-size:3rem;margin-bottom:8px;font-weight:700;letter-spacing:-0.02em;">AI Synthesis Engine</h1>
<p style="font-family:'Inter',sans-serif;font-size:14px;color:#6b7280;font-weight:300;max-width:600px;margin:0 auto;">Deep academic analysis powered by neural retrieval.</p>
</div>
</div>"""
