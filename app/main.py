"""
SME Research Assistant - Streamlit Chat Application

Main entry point for the web interface.
Refactored to use modular components for maintainability.
"""

import streamlit as st
import streamlit.components.v1 as components
import sys
import logging
from pathlib import Path
import time as sys_time


# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import modular components
from app.styles import inject_theme_css, inject_processing_overlay, remove_processing_overlay, inject_monitor_css
from app.state import SessionManager
from app.auth_helper import is_authenticated, get_current_user, logout, init_auth_state
from app.pages.auth import render_auth_page
from src.pipeline.loader import load_rag_pipeline_core # Headless Loader
from app.components import (
    render_sidebar,
    render_status_block,
    render_progress_steps,
    render_progress_block,
    render_welcome_screen,
    SVG_ICONS
)
from app.components.rag_wrapper import RAGWrapper, RetrieverWrapper
from app.components.quick_upload import get_quick_upload_context

# Import Live Monitor components
from src.ui.monitor_components import (
    init_monitor,
    start_monitor,
    add_step,
    complete_step,
    finish_monitor,
    render_monitor,
    inject_monitor_update,
    set_total_steps,
    add_warning,
)

from src.utils.diagnostics import DiagnosticGate, report_diagnostic # Diagnostic System

from src.utils.helpers import load_config
from src.retrieval import create_hybrid_search, create_reranker, create_context_builder
from src.generation import create_ollama_client, create_prompt_builder
from src.indexing import create_bm25_index
from src.indexing.qdrant_optimizer import run_startup_optimization


# Debug logging
import sys
# Configure root logger to output INFO logs to stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
    force=True # Force reconfiguration in case Streamlit already set it
)

# Define logger for this module
logger = logging.getLogger(__name__)

# Page configuration must be first Streamlit command
st.set_page_config(
    page_title="SME Research Assistant",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={} # Clean menu
)

# Inject CSS from external file (replaces 176 lines of inline CSS)
inject_theme_css()


def init_session_state():
    """Initialize session state variables using centralized manager."""
    SessionManager.init()
    
    # Additional legacy state (for backwards compatibility)
    if "rag_pipeline" not in st.session_state:
        st.session_state.rag_pipeline = None
    if "current_step" not in st.session_state:
        st.session_state.current_step = 0
    if "completed_main_pills" not in st.session_state:
        st.session_state.completed_main_pills = []
    if "section_progress" not in st.session_state:
        st.session_state.section_progress = (0, 0)



def check_auth():
    """JWT-based authentication via auth service."""
    # Initialize auth state
    init_auth_state()

    # Inject JavaScript to restore auth from localStorage on page load
    # This runs on EVERY page load to ensure session persistence works
    # The script checks localStorage and redirects with the refresh token in query params
    # which is then picked up by _try_restore_from_storage() on the next load
    st.markdown('''
    <script>
        (function() {
            // Only run once per page load
            if (window._sme_auth_restore_checked) return;
            window._sme_auth_restore_checked = true;

            const refreshToken = localStorage.getItem('sme_refresh_token');
            if (refreshToken && !window.location.search.includes('_auth_refresh')) {
                // Redirect with refresh token in query params
                const url = new URL(window.location.href);
                url.searchParams.set('_auth_refresh', refreshToken);
                window.location.href = url.toString();
            }
        })();
    </script>
    ''', unsafe_allow_html=True)

    # Check if user is authenticated
    if is_authenticated():
        return True

    # Not authenticated - show login/register page
    render_auth_page()
    return False


def check_clarification_needed(query: str, ollama_client, model: str) -> str | None:
    """Check if the query needs clarification before processing.

    Returns:
        Clarification question string, or None if no clarification needed.
    """
    try:
        from src.utils.helpers import load_config
        import yaml
    
        # Load clarification prompt
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            prompts = yaml.safe_load(f)
    
        clarification_prompt = prompts.get("clarification_check", "")
        if not clarification_prompt:
            return None
    
        # Format prompt with query
        formatted_prompt = clarification_prompt.format(query=query)
    
        # Call LLM
        response = ollama_client.generate(
            prompt=formatted_prompt,
            model=model,
            max_tokens=200,
            temperature=0.1
        )
    
        # Parse response
        if "CLARIFICATION_NEEDED:" in response:
            # Extract the clarifying question
            clarifying_q = response.split("CLARIFICATION_NEEDED:")[-1].strip()
            return clarifying_q
    
        return None
    
    except Exception as e:
        # If clarification check fails, continue without it
        logger.warning(f"Clarification check failed: {e}")
        return None


@st.cache_resource(show_spinner=False)
def load_rag_pipeline():
    """Load RAG pipeline components (Cached Globally)."""
    # Session state check removed, st.cache_resource handles singleton


    try:
        # Load components using the core loader (headless-compatible)
        pipeline = load_rag_pipeline_core("config/config.yaml")

        # Add wrappers for new UI logic (Retriever & RAG Orchestrator)
        # These are UI-specific wrappers, so they stay here
        pipeline["retriever"] = RetrieverWrapper(pipeline["hybrid_search"])
        pipeline["rag"] = RAGWrapper(pipeline)
    
        return pipeline
        
    except Exception as e:
        report_diagnostic(
            message=f"Failed to load RAG pipeline: {e}",
            error=e,
            severity="critical",
            context={"step": "load_rag_pipeline"}
        )
        # Do NOT call st.* here — cache_resource runs outside any layout context
        # and replaying a cached st.error() on a different layout block causes:
        # "streamlit element is called on some layout block created outside the function"
        logger.critical(f"Failed to load RAG pipeline: {e}")
        return None


def process_query(query: str, pipeline: dict, model: str = "gpt-oss:120b-cloud", 
                  depth: str = "Medium", paper_range: tuple = None,
                  citation_density: str = None, auto_citation_density: bool = True) -> tuple:
    """
    Process a user query through the RAG pipeline with HyDE enhancement.

    Args:
        query: User's research question
        pipeline: RAG pipeline components
        model: LLM model to use
        depth: "Low", "Medium", or "High" research depth
        paper_range: (min_papers, max_papers) tuple, or None to use depth preset
        citation_density: "Low", "Medium", or "High" citation density
        auto_citation_density: If True, AI decides citation density based on query
    
    Returns:
        Tuple of (response, sources, confidence, apa_references, compliance_badge, doi_to_number)
    """
    try:
        # Get depth preset hyperparameters
        from src.config.depth_presets import get_depth_preset
        preset = get_depth_preset(depth)
    
        top_k_initial = preset["top_k_initial"]
        top_k_rerank = preset["top_k_rerank"]
        max_tokens = preset["max_tokens"]
        use_hyde = preset["use_hyde"]
        use_query_expansion = preset.get("use_query_expansion", True)
        min_unique_papers = preset["min_unique_papers"]
        max_per_doi = preset["max_per_doi"]
        temperature = preset["temperature"]
    
        # Step 0: Query Expansion (skip for Low depth)
        sub_queries = [query]
        if use_query_expansion:
            from src.retrieval import create_query_expander
            expander = create_query_expander(llm_client=pipeline.get("llm"))
            sub_queries = expander.decompose_query(query, model=model)
    
        # Step 1: Search (HyDE optional based on depth)
        hybrid_search = pipeline["hybrid_search"]
        all_results = []
    
        if use_hyde:
            from src.retrieval import create_hyde_retriever
            try:
                hyde = create_hyde_retriever(
                    llm_client=pipeline["llm"],
                    embedder=hybrid_search.embedder,
                    vector_store=hybrid_search.vector_store,
                    top_k=top_k_initial
                )
                hyde_results = hyde.search(query, use_hyde=True, model=model)
                all_results.extend(hyde_results)
            except Exception as e:
                print(f"HyDE failed, falling back: {e}")
    
        # Standard search for all sub-queries
        for sub_q in sub_queries:
            sub_results = hybrid_search.search(sub_q, top_k=top_k_initial // max(1, len(sub_queries)))
            all_results.extend(sub_results)
    
        # Deduplicate by chunk_id
        seen_ids = set()
        unique_results = []
        for r in all_results:
            if r.chunk.chunk_id not in seen_ids:
                seen_ids.add(r.chunk.chunk_id)
                unique_results.append(r)
        results = unique_results
    
        if not results:
            return "I couldn't find any relevant information in the papers.", [], "LOW", [], "⚪ N/A", {}
    
        # Step 2: Rerank
        reranker = pipeline["reranker"]
        reranked = reranker.rerank(query, results, top_k=top_k_rerank)
    
        # Step 3: Build context with depth-aware parameters
        context_builder = pipeline["context_builder"]
    
        # Use paper_range if provided, otherwise use preset
        if paper_range:
            min_papers, max_papers = paper_range
        else:
            min_papers = min_unique_papers
            max_papers = min_unique_papers * 2  # Default max is 2x min
    
        context, used_results, apa_references, doi_to_number = context_builder.build_context(
            reranked,
            max_per_doi=max_per_doi,
            min_unique_papers=min_papers,
            max_unique_papers=max_papers
        )
    
        # Step 4: Generate response with depth-specific tokens
        prompt_builder = pipeline["prompt_builder"]
        base_prompt = prompt_builder.build_rag_prompt(
            query=query,
            context=context,
            conversation_history=st.session_state.messages[-6:]
        )
    
        # Add DYNAMIC citation density instructions based on question complexity
        try:
            from src.utils.citation_density import get_citation_instructions, calculate_citation_target
        
            # Calculate citation targets based on question complexity
            citation_info = calculate_citation_target(
                query=query,
                depth=depth,
                density_level=citation_density if citation_density else "Medium",
                auto_decide=auto_citation_density
            )
        
            # Log citation targets for debugging
            print(f"[Citation Density] Target: {citation_info['target_citations']} | "
                  f"Complexity: {citation_info['complexity']} | "
                  f"Response Length: {citation_info['response_length']}")
        
            # Get dynamic instructions
            citation_instr = get_citation_instructions(
                query=query,
                depth=depth,
                density_level=citation_density if citation_density else "Medium",
                auto_decide=auto_citation_density
            )
            prompt = base_prompt + citation_instr
        
        except ImportError as e:
            print(f"Citation density module not available: {e}")
            # Fallback to basic instructions
            prompt = base_prompt + """

CITATION REQUIREMENTS:
- Cite all factual claims, statistics, and findings with appropriate sources
- Use (Author, Year) or [N] format matching the provided sources
- Aim for diverse citations from multiple papers"""
    
        llm = pipeline["llm"]
        response = llm.generate(
            prompt=prompt,
            system_prompt=prompt_builder.system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model
        )
    
        # Step 5: Validate citation compliance
        try:
            from src.generation import validate_response, get_compliance_badge
            with DiagnosticGate("Final Validation", severity="warning") as gate:
                validation = validate_response(response, num_sources=len(used_results))
                citation_compliance = validation.compliance_score
                gate.context["score"] = validation.compliance_score
            compliance_badge = get_compliance_badge(citation_compliance)
        except Exception as e:
            # Already handled by gate but ensure flow continues
            print(f"Citation validation failed: {e}")
            citation_compliance = None
            compliance_badge = "⚪ N/A"
    
        # Determine confidence based on source diversity AND citation compliance
        unique_dois = set(r.chunk.doi for r in used_results)
        base_confidence = "HIGH" if len(unique_dois) >= 5 else "MEDIUM" if len(unique_dois) >= 2 else "LOW"
    
        # Adjust confidence if citation compliance is poor
        if citation_compliance is not None and citation_compliance < 0.5:
            if base_confidence == "HIGH":
                base_confidence = "MEDIUM"
            elif base_confidence == "MEDIUM":
                base_confidence = "LOW"
    
        confidence = base_confidence
    
        # Extract sources with paper-level numbering
        sources = []
        for r in used_results:
            doi = r.chunk.doi
            paper_num = doi_to_number.get(doi, 0)  # Get paper number from map
        
            # Use full APA reference if available, fallback to short citation
            apa_ref = r.chunk.metadata.get("apa_reference", "")
            short_citation = r.chunk.metadata.get("citation_str", f"[{doi}]")
        
            # Apply text cleaning to preview
            try:
                from src.utils.text_cleaner import clean_text
                preview = clean_text(r.chunk.text[:300]) + "..."
            except ImportError:
                preview = r.chunk.text[:300] + "..."
        
            sources.append({
                "paper_num": paper_num,  # Paper number matching reference list
                "citation": short_citation,
                "apa_reference": apa_ref,
                "title": r.chunk.metadata.get("title", r.chunk.section),
                "doi": doi,
                "score": r.score,
                "preview": preview
            })
    
        return response, sources, confidence, apa_references, compliance_badge, doi_to_number
    
    except Exception as e:
        # Report critical failure to monitor
        from src.utils.diagnostics import report_diagnostic
        report_diagnostic(
            name="Query Processing Crash",
            severity="critical",
            context={"error": str(e)},
            remediation="Check logs for traceback. System functionality may be degraded."
        )
        return f"Error processing query: {str(e)}", [], "LOW", [], "⚪ N/A", {}


def display_sources(sources: list, apa_references: list = None, response_text: str = None):
    """Display source documents with full APA references (split into Cited vs Additional).

    Args:
        sources: List of source dictionaries with DOI, title, preview, etc.
        apa_references: List of full APA reference strings
        response_text: The LLM response text to check for citation mentions
    """
    if not sources:
        return

    # Count unique papers
    unique_dois = set(s.get('doi', '') for s in sources)

    # REFERENCES SECTION (First - expanded by default)
    with st.expander(f"📖 Retrieved Sources ({len(apa_references or [])} papers, APA 7)", expanded=False):
        if apa_references:
            # References are now flawlessly split and appended natively to the response text.
            # This UI element just serves as a background list of all retrieved papers.
            for i, ref in enumerate(apa_references, 1):
                st.markdown(f"**[{i}]** {ref}")
        else:
            st.markdown("*No references available*")

    # EXCERPTS SECTION (Second - collapsed by default)
    with st.expander(f"📄 Source Excerpts ({len(sources)} from {len(unique_dois)} papers)", expanded=False):
        for source in sources:
            paper_num = source.get('paper_num', 0)
            # Handle different source formats (regular vs sequential RAG)
            citation = source.get('citation', source.get('title', 'Unknown source'))
            title = source.get('title', '')[:100]
            score = source.get('score', source.get('relevance', 0.0))
            preview = source.get('preview', source.get('text', 'No preview available'))
        
            st.markdown(f"""
            **[{paper_num}] {citation}**  
            *{title}...* | Relevance: {score:.3f}
        
            > {preview}
        
            ---
            """)


# render_sidebar() moved to app/components/sidebar.py


def main():
    """Main application."""
    # Health check bypass (for monitoring systems)
    if "health" in st.query_params:
        from datetime import datetime
        st.success("System operational")
        st.json({
            "status": "healthy",
            "service": "streamlit",
            "timestamp": datetime.now().isoformat()
        })
        st.stop()
        return

    # CONFIGURABLE MONITOR DIMENSIONS
    MONITOR_WIDTH_PX = 518         # Golden Ratio: 320px (Sidebar) * 1.618 = 517.76
    MONITOR_TOP_OFFSET_PX = 62     # Golden Ratio: 100px / 1.618 = 61.8
    MONITOR_BOTTOM_MARGIN_PX = 10  # Fibonacci: ~10px
    MONITOR_RIGHT_MARGIN_PX = 20   # Fibonacci: ~21px (But 20 is cleaner for alignment)
    
    # Calculated Padding: Width + (Gap on both sides to center main content)
    # Actually, to align left of monitor: Width + Gap
    MAIN_CONTENT_PADDING_RIGHT = MONITOR_WIDTH_PX + MONITOR_RIGHT_MARGIN_PX
    
    # CHAT MESSAGE POSITIONING (Processing State)
    # Adjust these values to move chat messages horizontally:
    CHAT_AI_LEFT_OFFSET_PX = 0       # Distance from left edge to AI message start (blue line)
    CHAT_USER_RIGHT_OFFSET_PX = 0    # Distance from right edge to user message end (red line)

    init_session_state()
    
    # Authenticate
    if not check_auth():
        return
    # logger.info("⚠️ AUTH BYPASSED FOR TESTING - AUTOMATED STARTUP VERIFICATION")

    # Call Sidebar
    sidebar_config = render_sidebar()

    # Inject sidebar overlay logic + body class for processing state
    if st.session_state.is_processing:
        st.markdown("""
        <script>
        // Add processing state class to body for CSS targeting
        document.body.classList.add('sme-processing');
        // Create sidebar overlay
        if (!document.getElementById('sidebar-overlay')) {
            const overlay = document.createElement('div');
            overlay.id = 'sidebar-overlay';
            overlay.className = 'sidebar-overlay';
            overlay.innerHTML = `<div class="sidebar-overlay-text">⏳ Query in Progress...</div><div class="sidebar-overlay-subtext">Click STOP to cancel</div>`;
            document.body.appendChild(overlay);
        }
        </script>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""<script>
        document.body.classList.remove('sme-processing');
        const overlay = document.getElementById('sidebar-overlay'); if (overlay) overlay.remove();
        </script>""", unsafe_allow_html=True)

    # CSS for fixed right panel layout
    st.markdown(f"""
    <style>
        /* CSS Updated: {sys_time.time()} */
        /* Create fixed right panel layout */
        #live-monitor-panel {{
            position: fixed !important;
            top: {MONITOR_TOP_OFFSET_PX}px !important;
            right: {MONITOR_RIGHT_MARGIN_PX}px !important;
            width: {MONITOR_WIDTH_PX}px !important;
            height: calc(100vh - {MONITOR_TOP_OFFSET_PX + MONITOR_BOTTOM_MARGIN_PX}px) !important;
            overflow-y: hidden !important; /* Internal scrolling handles content */
            display: flex !important;
            flex-direction: column !important;
            z-index: 999 !important;
            background: #0f0f0f !important;
            border-radius: 8px !important;
            border: 1px solid #2a2a2a !important;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4) !important;
        }}
        
        /* FIXED: Adjust main content to not overlap with monitor */
        /* Target both stMainBlockContainer and stAppViewBlockContainer for compatibility */
        .stMain .block-container,
        .stMainBlockContainer,
        [data-testid="stMainBlockContainer"],
        .stAppViewBlockContainer,
        [data-testid="stAppViewBlockContainer"] {{
            /* Container is ALREADY inside the main view (after sidebar), so don't subtract 320px */
            max-width: calc(100% - {MAIN_CONTENT_PADDING_RIGHT}px) !important;
            width: calc(100% - {MAIN_CONTENT_PADDING_RIGHT}px) !important;
            margin-left: 0 !important;
            margin-right: auto !important;  /* Push to left */
            padding-left: 20px !important;
            padding-right: 20px !important;
            box-sizing: border-box !important;
            align-self: flex-start !important;  /* Force left alignment in parent flex */
            position: relative !important;
            left: 0 !important;
        }}
        
        /* Ensure parent also respects limits */
        .stMain, .stAppViewContainer, [data-testid="stAppViewContainer"] {{
            max-width: 100vw !important;
            overflow-x: hidden !important;
        }}
        
        /* Ensure children take full width (but constrained by their own max-width) */
        [data-testid="stMainBlockContainer"] > div,
        [data-testid="stAppViewBlockContainer"] > div {{
            width: 100% !important;
            max-width: 100% !important;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        
        /* Ensure sidebar doesn't affect monitor */
        [data-testid="stSidebar"] {{
            z-index: 998 !important;
        }}
        
        /* ===== PROCESSING STATE: CHAT LAYOUT ===== */
        /* CSS Custom Properties for configurable chat positioning */
        :root {{
            --chat-ai-left-offset: {CHAT_AI_LEFT_OFFSET_PX}px;
            --chat-user-right-offset: {CHAT_USER_RIGHT_OFFSET_PX}px;
        }}
        
        /* PROCESSING STATE DETECTION: Use :has() to detect when processing IDs exist */
        /* When a chat message with proc-*-msg ID exists, expand parent containers */
        
        /* Force full-width on stMainBlockContainer child when processing */
        [data-testid="stMainBlockContainer"]:has(#proc-user-msg) > div,
        [data-testid="stMainBlockContainer"]:has(#proc-ai-msg) > div,
        [data-testid="stAppViewBlockContainer"]:has(#proc-user-msg) > div,
        [data-testid="stAppViewBlockContainer"]:has(#proc-ai-msg) > div {{
            align-items: stretch !important;
        }}
        
        /* Force full-width on vertical blocks when processing */
        [data-testid="stVerticalBlock"]:has(#proc-user-msg),
        [data-testid="stVerticalBlock"]:has(#proc-ai-msg) {{
            width: 100% !important;
            max-width: 100% !important;
            align-items: stretch !important;
        }}
        
        /* Force full-width on element containers when processing */
        .stElementContainer:has(#proc-user-msg),
        .stElementContainer:has(#proc-ai-msg),
        .stElementContainer:has([data-testid="stChatMessage"]) {{
            width: 100% !important;
            max-width: 100% !important;
        }}
        
        /* AI Message: Left-aligned (use blue line offset) */
        [data-testid="stChatMessage"]:has(#proc-ai-msg),
        [data-testid="stChatMessage"]:has(.layout-ai) {{
            width: 100% !important;
            justify-content: flex-start !important;
            padding-left: var(--chat-ai-left-offset) !important;
            box-sizing: border-box !important;
        }}
        
        /* User Message: Right-aligned with icon adjacent to message */
        [data-testid="stChatMessage"]:has(#proc-user-msg),
        [data-testid="stChatMessage"]:has(.layout-user) {{
            width: 100% !important;
            flex-direction: row-reverse !important;
            justify-content: flex-start !important;
            align-items: flex-start !important;
            gap: 8px !important;  /* Same gap as AI message */
            padding-right: var(--chat-user-right-offset) !important;
            box-sizing: border-box !important;
        }}
        
        /* Ensure user message content hugs the text and doesn't push away from avatar */
        [data-testid="stChatMessage"]:has(#proc-user-msg) > div,
        [data-testid="stChatMessage"]:has(.layout-user) > div {{
            margin: 0 !important;
            flex: 0 1 auto !important; /* Don't grow to fill space */
            width: fit-content !important; /* Only take necessary width */
            max-width: 80% !important;
        }}
        
        /* Ensure user message content doesn't have extra margin */
        [data-testid="stChatMessage"]:has(#proc-user-msg) > div {{
            margin: 0 !important;
        }}
    </style>
    """, unsafe_allow_html=True)

    # Inject monitor CSS
    inject_monitor_css()
    
    # Initialize monitor state (no rendering)
    init_monitor()
    
    # Render monitor panel (handled by init_monitor)
    # init_monitor() creates the placeholder and renders initial state

    # Load pipeline (before chat content)
    if st.session_state.get("pipeline_loaded", False) is False:
        video_placeholder = st.empty()
        
        loading_ui = """<div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 60vh;">
<h3 style="color: #f59e0b; font-family: 'Inter', sans-serif; font-weight: 500; margin-top: 20px;">Initializing AI Models & Processing Pipelines...</h3>
<p style="color: #6b7280; font-family: 'Inter', sans-serif; font-size: 14px;">This may take several minutes if Qdrant is performing background hardware optimization.</p>
</div>"""
        video_placeholder.markdown(loading_ui, unsafe_allow_html=True)
        
        # This synchronous call freezes the python thread while loading, 
        # but the browser keeps the CSS/HTML video playing smoothly
        pipeline = load_rag_pipeline()
        
        # Clear video placeholder and set loaded flag so it doesn't flash on reruns
        video_placeholder.empty()
        st.session_state["pipeline_loaded"] = True
    else:
        pipeline = load_rag_pipeline()

    if pipeline is None:
        st.warning("⚠️ RAG pipeline not loaded. Please ensure all services are running.")
        st.info("Run: `python scripts/ingest_papers.py --limit 100` to index papers first.")
        return

    # Main chat area (no column context needed - CSS handles layout)
    chat_container = st.container()
    with chat_container:
        # Welcome Screen (State A: Home)
        if not st.session_state.messages and not st.session_state.is_processing:
            with st.container():
                # Use the extracted welcome screen component
                render_welcome_screen()
                
                # CUSTOM INPUT: Styled search bar with Send button
                
                # PREVENT AUTOCOMPLETE: Inject JS to disable suggestions
                components.html(
                    """
                    <script>
                        // Continuous check to force autocomplete off
                        function disableAutocomplete() {
                            const inputs = window.parent.document.querySelectorAll('input[type="text"]');
                            inputs.forEach(input => {
                                input.setAttribute('autocomplete', 'off');
                                input.setAttribute('data-form-type', 'other');
                            });
                        }
                        
                        // Run immediately and on changes
                        disableAutocomplete();
                        const observer = new MutationObserver(disableAutocomplete);
                        observer.observe(window.parent.document.body, { childList: true, subtree: true });
                    </script>
                    """,
                    height=0, width=0
                )

                st.markdown("""
                <style>
                    /* ===== UNIFIED SEARCH BOX - Single Border Design ===== */
                    
                    /* Outer form container - THE ONLY VISIBLE BOX */
                    [data-testid="stForm"] {
                        max-width: 48rem !important;
                        width: 100% !important;
                        margin: 0 auto !important;
                        background: #1a1a1a !important;
                        border: 1px solid #333 !important;
                        border-radius: 12px !important;
                        padding: 8px 8px 8px 16px !important; /* Equal padding top/bottom/right (8px) to frame the button */
                        min-height: auto !important; /* Let padding define height (36+16=52px) */
                        display: flex !important;
                        align-items: center !important; /* Flex align center */
                    }
                    
                    /* Remove ALL inner container styling & Margins */
                    [data-testid="stForm"] * {
                        vertical-align: middle !important;
                    }

                    [data-testid="stForm"] > div,
                    [data-testid="stForm"] > div > div,
                    [data-testid="stForm"] [data-testid="stHorizontalBlock"],
                    [data-testid="stForm"] [data-testid="stVerticalBlock"],
                    [data-testid="stForm"] [data-testid="column"] {
                        background: transparent !important;
                        border: none !important;
                        padding: 0 !important;
                        margin: 0 !important;
                        gap: 0 !important;
                        display: flex !important;
                        align-items: center !important; /* Force everything to center */
                        height: 100% !important;
                    }
                    
                    /* Horizontal layout for input + button */
                    [data-testid="stForm"] > div {
                        display: flex !important;
                        flex-direction: row !important;
                        width: 100% !important;
                    }
                    
                    /* Text input wrapper */
                    [data-testid="stForm"] [data-testid="stTextInput"],
                    [data-testid="stForm"] [data-testid="stTextInput"] div,
                    [data-testid="stForm"] [data-testid="stTextInput"] input {
                        background: transparent !important;
                        border: none !important;
                        box-shadow: none !important;
                        flex: 1 !important;
                        height: 100% !important;
                        display: flex !important;
                        align-items: center !important;
                        border-radius: 0 !important; /* Ensure no rounded corners on inner bits */
                    }
                    
                    /* The actual input element */
                    [data-testid="stForm"] input {
                        padding: 0 !important; /* Remove input padding */
                        margin: 0 !important;
                        color: #e0e0e0 !important; /* Ensure text is visible light grey */
                        font-size: 15px !important;
                        outline: none !important;
                        line-height: normal !important;
                        height: 100% !important;
                        width: 100% !important;
                    }
                    
                    [data-testid="stForm"] input:focus {
                        box-shadow: none !important;
                        border: none !important;
                        outline: none !important;
                    }
                    
                    [data-testid="stForm"] input::placeholder {
                        color: #6b7280 !important;
                        line-height: normal !important;
                    }
                    
                    /* Hide ALL labels */
                    [data-testid="stForm"] .stTextInput > label,
                    [data-testid="stForm"] .stTextInput div[data-testid="stMarkdownContainer"] {
                        display: none !important;
                        height: 0 !important;
                        margin: 0 !important;
                        padding: 0 !important;
                        min-height: 0 !important;
                    }
                    
                    /* Submit button wrapper */
                    [data-testid="stForm"] [data-testid="stFormSubmitButton"],
                    [data-testid="stForm"] [data-testid="stFormSubmitButton"] > div {
                        background: transparent !important;
                        border: none !important;
                        padding: 0 !important;
                        margin: 0 !important;
                        display: flex !important;
                        align-items: center !important;
                        height: 100% !important;
                        justify-content: flex-end !important; /* Align button to the right */
                    }
                    
                    /* The actual button - Flexbox Centering Container */
                    [data-testid="stForm"] button[type="submit"],
                    [data-testid="stForm"] [data-testid="stFormSubmitButton"] button {
                        display: flex !important; 
                        align-items: center !important;
                        justify-content: center !important;
                        visibility: visible !important;
                        width: 36px !important;
                        height: 36px !important;
                        min-width: 36px !important;
                        padding: 0 !important;
                        border: none !important;
                        background: #333 !important;
                        border-radius: 8px !important;
                        cursor: pointer !important;
                        transition: all 0.2s !important;
                        margin-bottom: 0 !important;
                        margin-left: auto !important;
                        margin-right: 0 !important;
                    }
                    
                    /* Hide ALL internal children of the button to prevent alignment interference */
                    [data-testid="stForm"] button[type="submit"] > *,
                    [data-testid="stForm"] [data-testid="stFormSubmitButton"] button > * {
                        display: none !important;
                    }
                    
                    [data-testid="stForm"] button[type="submit"]:hover,
                    [data-testid="stForm"] [data-testid="stFormSubmitButton"] button:hover {
                        background: #f59e0b !important;
                        color: black !important; /* This color applies to text/icon */
                    }
                    
                    /* SVG ARROW ICON - The Forever Fix */
                    [data-testid="stForm"] button[type="submit"]::after,
                    [data-testid="stForm"] [data-testid="stFormSubmitButton"] button::after {
                        content: "" !important;
                        display: block !important;
                        width: 28px !important; /* Increased size from 20px */
                        height: 20px !important;
                        background-color: white !important; /* Icon Color */
                        -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cline x1='5' y1='12' x2='19' y2='12'%3E%3C/line%3E%3Cpolyline points='12 5 19 12 12 19'%3E%3C/polyline%3E%3C/svg%3E") !important;
                        mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cline x1='5' y1='12' x2='19' y2='12'%3E%3C/line%3E%3Cpolyline points='12 5 19 12 12 19'%3E%3C/polyline%3E%3C/svg%3E") !important;
                        -webkit-mask-size: contain !important;
                        mask-size: contain !important;
                        -webkit-mask-repeat: no-repeat !important;
                        mask-repeat: no-repeat !important;
                        -webkit-mask-position: center !important;
                        mask-position: center !important;
                        margin: 0 !important;
                    }
                    
                    [data-testid="stForm"] button[type="submit"]:hover::after,
                    [data-testid="stForm"] [data-testid="stFormSubmitButton"] button:hover::after {
                        background-color: black !important;
                    }

                    /* UI Polish: Hide Streamlit form input instructions "Press Enter to apply" */
                    [data-testid="InputInstructions"] {
                        display: none !important;
                    }

                    /* UI Polish: Make the text area resize handle invisible but still functional */
                    [data-testid="stTextArea"] textarea::-webkit-resizer {
                        background: transparent !important;
                    }

                    /* Fix stark white background on any standard chat inputs or file uploaders explicitly */
                    [data-testid="stChatInput"] {
                        background-color: #1a1a1a !important;
                        border-color: #404040 !important;
                    }
                    [data-testid="stChatInput"] * {
                        background-color: transparent !important;
                        color: #e0e0e0 !important;
                    }
                </style>
                """, unsafe_allow_html=True)
                
                # Use Streamlit form with arrow submit button
                with st.form("home_search_form", clear_on_submit=True):
                    # Use vertical_alignment='center' to ensure the columns align their contents (input & button)
                    col1, col2 = st.columns([12, 1], vertical_alignment="center")
                    with col1:
                        prompt_input = st.text_area(
                            "Research Query",
                            placeholder="Explore the literature",
                            label_visibility="collapsed",
                            key="home_input",
                            height=42
                        )
                    with col2:
                        submitted = st.form_submit_button("→", use_container_width=True)

                # UI Polish: Inject JS to perfectly auto-expand the textarea independently of Streamlit's React virtual DOM constraints.
                components.html(
                    """
                    <script>
                    const doc = window.parent.document;
                    
                    function attachAutoExpand() {
                        const textareas = doc.querySelectorAll('textarea[aria-label="Research Query"]');
                        
                        if (textareas.length === 0) {
                            setTimeout(attachAutoExpand, 100); // Retry if Streamlit hasn't rendered it yet
                            return;
                        }
                        
                        textareas.forEach(ta => {
                            if (!ta.dataset.autoExpand) {
                                ta.dataset.autoExpand = "true";
                                ta.style.overflowY = 'hidden';
                                
                                ta.addEventListener('input', function() {
                                    this.style.height = '42px'; // Temporarily shrink to measure
                                    
                                    const newHeight = Math.min(this.scrollHeight, 150);
                                    this.style.height = newHeight + 'px'; // Expand to content
                                    
                                    if (this.scrollHeight > 150) {
                                        this.style.overflowY = 'auto'; // Scroll when max hit
                                    } else {
                                        this.style.overflowY = 'hidden';
                                    }
                                });
                            }
                        });
                    }
                    
                    // Fire immediately
                    attachAutoExpand();
                    </script>
                    """,
                    height=0,
                    width=0
                )

                if submitted and prompt_input:
                    prompt = prompt_input
                else:
                    prompt = None

        else:
            # STATE B (Processing) / STATE C (Complete)
            if st.session_state.is_processing:
                # During processing: no input shown here
                # The processing container will be rendered INSIDE the AI chat_message block
                # after the status bar to ensure correct element ordering
                prompt = None

                # SIDEBAR LOCKING (Persistent)
                # Inject CSS to dim and disable sidebar during processing
                # Must be here to survive reruns. Sidebar stays visible so users
                # can see their quick uploads are still active.
                st.markdown("""
                <style>
                    [data-testid="stSidebar"] {
                        opacity: 0.7 !important;
                        pointer-events: none !important;
                        user-select: none !important;
                        transition: all 0.3s ease !important;
                    }
                </style>
                """, unsafe_allow_html=True)
            else:
                # STATE C: Complete - Show message history and follow-up input
                # NOTE: Layout is controlled by global CSS (lines 502-554). No overrides needed here.
                
                # Render all messages from history
                for msg in st.session_state.messages:
                    avatar = "👤" if msg["role"] == "user" else "🤖"
                    with st.chat_message(msg["role"], avatar=avatar):
                        content = msg.get("content", "")
                        # Render content with LaTeX support if available
                        try:
                            from src.utils.latex_renderer import render_with_latex
                            display_content = render_with_latex(content)
                            if not display_content or not display_content.strip():
                                display_content = content
                        except Exception:
                            display_content = content
                        # Inject layout marker for consistent styling
                        layout_marker = f'<span class="layout-{msg["role"]}" style="display:none"></span>'
                        st.markdown(layout_marker + display_content, unsafe_allow_html=True)
                
                # Follow-up question input (after history)
                prompt = st.chat_input("Ask a follow-up question...", key="chat_input_bottom")

        # UNIFIED PROCESSING LOGIC
        if prompt:
            # Snapshot config values for this query (immune to reruns)
            st.session_state.is_processing = True

            # Sidebar locking moved to persistent block (line 885) to resolve rerun bug.
            
            st.session_state.current_step = 0
            st.session_state.query_config = {

                "depth": sidebar_config.depth_level,
                "model": sidebar_config.selected_model,
                "paper_range": sidebar_config.paper_range,
                "auto_decide": sidebar_config.auto_decide_papers,
                "enable_sequential": sidebar_config.enable_sequential,
                "enable_section_mode": sidebar_config.enable_section_mode,
                "enable_clarification": sidebar_config.enable_clarification,
                "show_sources": sidebar_config.show_sources,
                "show_confidence": sidebar_config.show_confidence,
                "citation_density": sidebar_config.citation_density,
                "auto_citation_density": sidebar_config.auto_citation_density
            }

            # User sent a message
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.session_state.is_processing = True
            # Calculate expected steps
            if sidebar_config.enable_sequential:
                initial_steps = 6
            else:
                initial_steps = 5
                
            # Start the live monitor for new query
            start_monitor(total_expected_steps=initial_steps)
            
            # Rerun to show user message immediately
            st.rerun()

    # Query Processing Logic (State C: Responding)
    if st.session_state.is_processing and st.session_state.messages and st.session_state.messages[-1]["role"] == "user":      
            # HIDE WELCOME SCREEN ELEMENTS DURING PROCESSING (Issue #3)
            st.markdown("""
            <style>
                /* Hide welcome screen cards and form during processing */
                .glass-card { display: none !important; }
                [data-testid="stForm"] { display: none !important; }
                .welcome-title, .welcome-subtitle { display: none !important; }
                /* Hide the feature cards container */
                .stHorizontalBlock:has(.glass-card) { display: none !important; }
            </style>
            """, unsafe_allow_html=True)
            
            # ROOT FIX: Get prompt from last user message (prompt variable is None after st.rerun())
            prompt = st.session_state.messages[-1]["content"]
            
            # COMPREHENSIVE CSS FOR PROCESSING STATE - injected here to ensure it applies
            # SVGs URL-encoded for CSS background
            svg_user = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2'/%3E%3Ccircle cx='12' cy='7' r='4'/%3E%3C/svg%3E"
            svg_bot = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='%23f59e0b' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 8V4H8'/%3E%3Crect width='16' height='12' x='4' y='8' rx='2'/%3E%3Cpath d='M2 14h2'/%3E%3Cpath d='M20 14h2'/%3E%3Cpath d='M15 13v2'/%3E%3Cpath d='M9 13v2'/%3E%3C/svg%3E"
            
            st.markdown(f"""
            <style>
                /* CSS Updated: {sys_time.time()} */
                /* ISSUE #4 FIX: Prevent Overlap with Fixed Right Panel - Handled Globally now */
                
                /* ISSUE #1: Hide Grey Stop Buttons */
                .stButton button[kind="secondary"],
                .stButton > button,
                button[data-testid="baseButton-secondary"] {{
                    display: none !important;
                }}
                
                /* ISSUE #1 & #2: CUSTOM AVATARS */
                /* User Avatar */
                [data-testid="stChatMessage"]:has(#proc-user-msg) [data-testid="stChatMessageAvatar"] {{
                    background: #404040 !important;
                    border-radius: 50% !important;
                    /* margin-right: 20px !important; */ 
                }}
                /* Hide original emoji */
                [data-testid="stChatMessage"]:has(#proc-user-msg) [data-testid="stChatMessageAvatar"] img,
                [data-testid="stChatMessage"]:has(#proc-user-msg) [data-testid="stChatMessageAvatar"] div {{
                    display: none !important; 
                }}
                [data-testid="stChatMessage"]:has(#proc-user-msg) [data-testid="stChatMessageAvatar"]::after {{
                    content: "";
                    display: block;
                    width: 100%;
                    height: 100%;
                    background-image: url("{svg_user}");
                    background-repeat: no-repeat;
                    background-position: center;
                    background-size: 60%;
                }}
                
                /* AI Avatar */
                [data-testid="stChatMessage"]:has(#proc-ai-msg) [data-testid="stChatMessageAvatar"] {{
                    background: rgba(217, 119, 6, 0.2) !important;
                    border: 1px solid rgba(245, 158, 11, 0.3) !important;
                    border-radius: 50% !important;
                }}
                [data-testid="stChatMessage"]:has(#proc-ai-msg) [data-testid="stChatMessageAvatar"] img,
                [data-testid="stChatMessage"]:has(#proc-ai-msg) [data-testid="stChatMessageAvatar"] div {{
                    display: none !important;
                }}
                [data-testid="stChatMessage"]:has(#proc-ai-msg) [data-testid="stChatMessageAvatar"]::after {{
                    content: "";
                    display: block;
                    width: 100%;
                    height: 100%;
                    background-image: url("{svg_bot}");
                    background-repeat: no-repeat;
                    background-position: center;
                    background-size: 60%;
                }}

                /* User Message Bubble Styling */
                [data-testid="stChatMessage"]:has(#proc-user-msg) [data-testid="stMarkdownContainer"] {{
                    background: #262626 !important;
                    border: 1px solid #404040 !important;
                    border-radius: 16px 16px 4px 16px !important;
                    padding: 12px 16px !important;
                    max-width: 600px !important; 
                    color: #ffffff !important;
                    font-size: 16px !important;
                }}
                
                /* AI Message Bubble Styling */
                [data-testid="stChatMessage"]:has(#proc-ai-msg) [data-testid="stMarkdownContainer"] {{
                    max-width: 650px !important;
                }}
            </style>
            """, unsafe_allow_html=True)
            
            # DISPLAY USER MESSAGE with avatar (using empty char to rely on CSS replacement)
            with st.chat_message("user", avatar="👤"): 
                # INJECT HIDDEN ID for CSS targeting AND show prompt in same container
                st.markdown(f'<span id="proc-user-msg" class="layout-user" style="display:none;"></span>{prompt}', unsafe_allow_html=True)
            
            # Use snapshotted config
            cfg = st.session_state.get("query_config")
        
            # Defensive check for config
            if cfg is None:
                print("WARNING: session_state.query_config is None! Re-initializing from current state.")
                cfg = {
                    "depth": sidebar_config.depth_level,
                    "model": sidebar_config.selected_model,
                    "paper_range": (8, 20), # Safe default
                    "auto_decide": True,
                    "enable_sequential": sidebar_config.enable_sequential,
                    "enable_section_mode": sidebar_config.enable_section_mode,
                    "enable_clarification": sidebar_config.enable_clarification,
                    "show_sources": sidebar_config.show_sources,
                    "show_confidence": sidebar_config.show_confidence,
                    "citation_density": sidebar_config.citation_density,
                    "auto_citation_density": sidebar_config.auto_citation_density
                }
                st.session_state.query_config = cfg
        
            # Determine paper range (AI or manual)
            if cfg["auto_decide"] or cfg["paper_range"] is None:
                try:
                    from src.utils.question_classifier import get_paper_range, get_classification_info
                    actual_paper_range = get_paper_range(prompt, cfg["depth"], auto_decide=True)
                    classification_info = get_classification_info(prompt, cfg["depth"])
                except Exception:
                    actual_paper_range = (8, 20)
                    classification_info = None
            else:
                actual_paper_range = cfg["paper_range"]
                classification_info = None

            # MULTI-USER: Extract user_id for data isolation
            current_user = get_current_user()
            user_id = current_user.id if current_user else None
            if user_id:
                logger.debug(f"[MULTI-USER] Processing query for user_id={user_id}")
            else:
                logger.warning("[MULTI-USER] No user_id found - query will access ALL data (legacy mode)")

            # Clarification Check (if enabled)
            if cfg["enable_clarification"]:
                try:
                    clarifying_question = check_clarification_needed(
                        prompt, 
                        pipeline["llm"],  # Fixed: key is 'llm' not 'ollama_client'
                        cfg["model"]
                    )
                    if clarifying_question:
                        # Show clarification question and wait for user input
                        with st.chat_message("assistant"):
                            st.info(f"🤔 **Clarification Needed:**\n\n{clarifying_question}")
                            st.caption("Please refine your question above and submit again.")
                    
                        # Store clarification state and exit early
                        st.session_state.is_processing = False
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": f"🤔 **Clarification Needed:**\n\n{clarifying_question}\n\n*Please refine your question above and submit again.*",
                            "is_clarification": True
                        })
                        st.rerun()
                except Exception as e:
                    st.caption(f"⚠️ Clarification check skipped: {e}")
    
            # Generate response - AI Avatar changed to 🤖 (Fix #3)
            with st.chat_message("assistant", avatar="🤖"):
                # INJECT HIDDEN ID for CSS targeting
                st.markdown('<span id="proc-ai-msg" class="layout-ai" style="display:none;"></span>', unsafe_allow_html=True)
                depth_emoji = {"Low": "⚡", "Medium": "⚙️", "High": "🔬"}
                seq_indicator = " + 🔄 Sequential" if cfg["enable_sequential"] else ""
                
                # Initialize variables to ensure scope across blocks
                reflection_log_data = [] 
            
                # Define steps based on mode
                if cfg["enable_sequential"]:
                    steps = ["Expanding", "Searching", "🔄 Reasoning", "Generating", "Validating"]
                else:
                    steps = ["Expanding", "Searching", "Reranking", "Generating", "Validating"]
            
                # FIX #8: Hide progress pills - use empty placeholder that won't render pills
                progress_placeholder = st.empty()
                # progress_placeholder.markdown(render_progress_steps(0, steps, "Preparing query..."), unsafe_allow_html=True)
            
                # Status row placeholder for dynamic updates - styled as mockup
                status_placeholder = st.empty()
            
                # PROCESSING CONTAINER - Rendered AFTER status bar for correct ordering
                processing_container = st.empty()
                # Native Streamlit Implementation - Clean & Robust
                with processing_container.container():
                    # Verified Working Stop Mechanism: Checkbox
                    # (Buttons are hidden by global CSS, Checkbox survives)
                    if st.checkbox("🛑 Stop Generation", key="stop_gen_checkbox"):
                        st.session_state.stop_requested = True
                        st.session_state.is_processing = False
                        st.rerun()
                        
                    st.empty() # Spacer
            
                # Define total steps for progress calculation
                total_steps = len(steps)
            
                # SVGs for Status Blocks
                SVG_ANALYZE = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>'
                SVG_SEARCH = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>'
                SVG_RERANK = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"></path></svg>'
                SVG_GENERATE = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"></path></svg>'
                SVG_WRITE = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>'
                SVG_VALIDATE = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>'
            
                # Step 1: Expanding (step 0)
                import time
                step_start_time = time.time()
                status_placeholder.markdown(
                    render_status_block(SVG_ANALYZE, "Analyzing Query", "Expanding semantic context..."), 
                    unsafe_allow_html=True
                )
                
                st.session_state.current_main_pill = 0
                st.session_state.current_sub_pill = 0
                
                # Live monitor - Query Expansion (actual step happening now)
                add_step("Analyzing Query")
                inject_monitor_update()
            
                # Step 2: Searching
                st.session_state.current_main_pill = 0
                complete_step()
                
                status_placeholder.markdown(
                    render_status_block(SVG_SEARCH, "Deep Research", f"Searching {actual_paper_range[1]} academic papers...", "active"), 
                )
                
                # Live monitor - Deep Research (actual step happening now)
                add_step(f"Searching {actual_paper_range[1]} papers")
                inject_monitor_update()
                
                reflection_log_data = [] # Initialize for scope safety

                if cfg["enable_sequential"]:
                    # Sequential Mode Logic
                    # NOTE: SequentialRAG handles its own multi-round search internally
                    # We do NOT pre-search here to avoid duplicate/wasted search
                    
                    st.session_state.current_main_pill = 1
                    status_placeholder.markdown(
                        render_status_block(SVG_RERANK, "Sequential Reasoning", "Initializing multi-round search...", "active"), 
                        unsafe_allow_html=True
                    )
                    # Monitor updates handled at end of processing
                    
                    # Check if section mode is enabled
                    if cfg.get("enable_section_mode", False):
                        # Section-by-section streaming generation
                        # FIX #1: Load and pass preset from depth configuration
                        from src.config.depth_presets import get_depth_preset
                        preset = get_depth_preset(cfg["depth"])
                        
                        # process_with_sections is a generator
                        section_gen = pipeline["rag"].sequential_rag.process_with_sections(
                            query=prompt,
                            depth=cfg["depth"],
                            model=cfg["model"],
                            paper_range=actual_paper_range,
                            conversation_history=st.session_state.get("messages", []),  # FIX #3: Pass conversation history
                            citation_density=cfg.get("citation_density"),
                            auto_citation_density=cfg.get("auto_citation_density", True),
                            preset=preset,  # FIX #1: Pass preset parameter
                            user_id=user_id,  # MULTI-USER: Pass user_id for data isolation
                            knowledge_source=cfg.get("knowledge_source", "both"),  # Knowledge source selection
                            quick_upload_context=get_quick_upload_context(),  # Quick uploads for section mode
                            status_callback=lambda step_name: (
                                status_placeholder.markdown(
                                    render_status_block(SVG_RERANK, "Processing", f"{step_name}", "active"),
                                    unsafe_allow_html=True
                                ),
                                # Monitor shows EXACT backend step name - no fake sub-steps
                                add_step(step_name),
                                # FIX: Update monitor via JS
                                inject_monitor_update()
                            )
                        )
                        
                        # FIX #2: Create container for progressive section streaming
                        section_container = st.empty()
                        accumulated_sections = []
                        
                        # Consume generator and display sections progressively
                        final_result = None
                        for progress in section_gen:
                            # NEW: Handle Evidence-First V2 Steps
                            if progress.type == "step":
                                status_placeholder.markdown(
                                    render_status_block(SVG_RERANK, progress.title, "Processing...", "active"),
                                    unsafe_allow_html=True
                                )
                                add_step(progress.title)
                                st.markdown(inject_monitor_update(), unsafe_allow_html=True)
                            
                            elif progress.type == "info":
                                # Add informational message to diagnostic center
                                add_warning(progress.title, type="success")
                                st.markdown(inject_monitor_update(), unsafe_allow_html=True)

                            # Existing handlers
                            elif progress.type == "warning":
                                st.warning(progress.content)
                                status_placeholder.markdown(
                                    render_status_block(SVG_WRITE, "⚠️ Warning", progress.content[:50] + "...", "active"),
                                    unsafe_allow_html=True
                                )
                                add_warning(progress.content)
                                st.markdown(inject_monitor_update(), unsafe_allow_html=True)
                            
                            elif progress.type == "outline":
                                status_placeholder.markdown(
                                    render_status_block(SVG_WRITE, "Research Outline", progress.content[:100] + "...", "active"),
                                    unsafe_allow_html=True
                                )
                                # Dynamically update expected steps with actual section count
                                set_total_steps(5 + progress.total_sections)
                                
                                # FIX #2: Show outline in chat area
                                with section_container:
                                    st.info(f"📋 **Research Outline**\n\n{progress.content}")
                            
                            elif progress.type == "section":
                                status_placeholder.markdown(
                                    render_status_block(SVG_WRITE, f"Section {progress.section_num}/{progress.total_sections}", 
                                                       progress.title, "active"),
                                    unsafe_allow_html=True
                                )
                                # Monitor update for section
                                add_step(f"Writing: {progress.title[:30]}...")
                                st.markdown(inject_monitor_update(), unsafe_allow_html=True)

                                # FIX #2: Stream section to chat immediately
                                accumulated_sections.append({
                                    "title": progress.title,
                                    "content": progress.content,
                                    "num": progress.section_num
                                })
                                
                                # Update chat display with all sections so far
                                with section_container:
                                    sections_html = ""
                                    for sec in accumulated_sections:
                                        # Use div to ensure opacity/color is standard and fix header visibility
                                        sections_html += f"""
## {sec['title']}

<div style="opacity: 1.0; color: inherit;">

{sec['content'].strip()}

</div>
\n\n"""
                                    st.markdown(sections_html, unsafe_allow_html=True)
                            
                            elif progress.type == "complete":
                                final_result = pipeline["rag"].sequential_rag._last_result
                                section_container.empty()  # Clear progressive display
                        
                        # FIX #4: Enhanced error handling with partial results
                        if final_result:
                            response = final_result.get("response", "")
                            sources = final_result.get("sources", [])
                            confidence = final_result.get("confidence", "MEDIUM")
                            apa_references = final_result.get("apa_references", [])
                            compliance_badge = final_result.get("compliance_badge", "⚪ N/A")
                            doi_to_number = final_result.get("doi_map", {})
                            reflection_log_data = []
                        else:
                            # FIX #4: Show partial results if generation incomplete
                            error_details = []
                            
                            # Check what sections completed
                            if accumulated_sections:
                                error_details.append(f"✅ Completed {len(accumulated_sections)} of {progress.total_sections if progress else '?'} sections")
                                partial_response = "\n\n".join([
                                    f"## {s['title']}\n\n{s['content']}" 
                                    for s in accumulated_sections
                                ])
                                error_details.append("\n\n⚠️ **Generation incomplete. Showing partial results:**\n\n")
                                response = "\n".join(error_details) + partial_response
                                sources, apa_references = [], []
                                confidence = "LOW"
                                compliance_badge = "⚠️ Incomplete"
                            else:
                                response = "❌ Section generation failed to start. Please try again with different settings or check the logs."
                                sources, apa_references = [], []
                                confidence = "LOW"
                                compliance_badge = "⚠️ Failed"
                            
                            doi_to_number = {}
                    else:
                        # Standard sequential mode (process_with_reflection)
                        response, sources, confidence, apa_references, compliance_badge, doi_to_number, reflection_log_data = pipeline["rag"].generate_sequential(
                            query=prompt,
                            model=cfg["model"],
                            depth=cfg["depth"],
                            paper_range=actual_paper_range,
                            citation_density=cfg.get("citation_density"),
                            auto_citation_density=cfg.get("auto_citation_density", True),
                            user_id=user_id,  # MULTI-USER: Pass user_id for data isolation
                            knowledge_source=cfg.get("knowledge_source", "both"),  # Knowledge source selection
                            status_callback=lambda step_name: (
                                status_placeholder.markdown(
                                    render_status_block(SVG_RERANK, "Sequential Reasoning", f"{step_name}...", "active"),
                                    unsafe_allow_html=True
                                ),
                                # Monitor update
                                add_step(step_name),
                                st.markdown(inject_monitor_update(), unsafe_allow_html=True)
                            )
                        )

                else:
                    # Standard RAG Logic (Non-Sequential)
                    # Route through RAGWrapper.generate() for consistency
                    
                    # 2. Search
                    st.session_state.current_sub_pill = 0
                    # Monitor updates happen at completion
                    
                    status_placeholder.markdown(
                        render_status_block(SVG_SEARCH, "Searching", "Hybrid search in progress...", "active"), 
                        unsafe_allow_html=True
                    )
                    
                    # Monitor update
                    add_step("Searching papers")
                    st.markdown(inject_monitor_update(), unsafe_allow_html=True)
                    
                    retrieval_results = pipeline["retriever"].retrieve(
                        prompt,
                        top_k=actual_paper_range[1],
                        user_id=user_id,
                        knowledge_source=cfg.get("knowledge_source", "both")
                    )
                    
                    # Live monitor - Search complete
                    complete_step()
                    step_start_time = time.time()
                    
                    # 3. Rerank & Generate via RAGWrapper
                    st.session_state.current_main_pill = 0
                    st.session_state.current_sub_pill = 1 # Rerank
                    
                    # Live monitor - Rerank (actual step happening now)
                    add_step("Reranking context")
                    st.markdown(inject_monitor_update(), unsafe_allow_html=True)
                        
                    status_placeholder.markdown(
                        render_status_block(SVG_RERANK, "Neural Reranking", "Optimizing context relevance...", "active"), 
                        unsafe_allow_html=True
                    )
                
                    # Use RAGWrapper.generate() instead of standalone process_query()
                    response, sources, confidence, apa_references, compliance_badge, doi_to_number, reflection_log_data = pipeline["rag"].generate(
                        query=prompt,
                        retrieved_context=retrieval_results,
                        model=cfg["model"],
                        depth=cfg["depth"],
                        paper_range=actual_paper_range,
                        citation_density=cfg.get("citation_density"),
                        auto_citation_density=cfg.get("auto_citation_density", True),
                        user_id=user_id
                    )
                    
                    # Live monitor - Rerank complete
                    complete_step()
                    step_start_time = time.time()
            
                # Step 4: Generating
                st.session_state.current_main_pill = 1
                st.session_state.current_sub_pill = 0
                
                # Live monitor - Generation
                add_step("Generating response")
                st.markdown(inject_monitor_update(), unsafe_allow_html=True)
                    
                status_placeholder.markdown(
                    render_status_block(SVG_WRITE, "Synthesizing Answer", f"Generating response with {cfg.get('model', 'AI')}...", "active"), 
                    unsafe_allow_html=True
                )
            
                # Step 5: Validating
                st.session_state.current_main_pill = 2
                st.session_state.current_sub_pill = 0
                
                # Live monitor - Verification (actual step happening now)
                add_step("Checking citation compliance")
                st.markdown(inject_monitor_update(), unsafe_allow_html=True)
                    
                status_placeholder.markdown(
                    render_status_block(SVG_VALIDATE, "Verification", "Checking citation compliance...", "active"), 
                    unsafe_allow_html=True
                )
            
                # Clear progress indicators
                # progress_placeholder.empty() # Removed: We use status_placeholder only 
                status_placeholder.empty()
            
                # Display confidence and citation compliance badges
                if cfg["show_confidence"]:
                    confidence_color = {
                        "HIGH": "🟢",
                        "MEDIUM": "🟡", 
                        "LOW": "🔴"
                    }
                    # Use apa_references count if available, otherwise count from sources
                    papers_used = len(apa_references) if apa_references else len(set(s.get("doi", "") for s in sources))
                    st.caption(f"{confidence_color.get(confidence, '⚪')} Confidence: {confidence} | Citation: {compliance_badge} | Papers: {papers_used}")

                    # Show quick upload attribution if files were used in this response
                    if st.session_state.get("quick_uploads"):
                        upload_count = len(st.session_state.quick_uploads)
                        upload_names = ", ".join([f["filename"] for f in st.session_state.quick_uploads[:2]])
                        if upload_count > 2:
                            upload_names += f" +{upload_count - 2} more"
                        st.caption(f"📎 Included {upload_count} uploaded doc{'s' if upload_count > 1 else ''}: {upload_names}")

                    # FIX: Monitor Complete
                    finish_monitor(sources_count=papers_used)
            
                # Apply LaTeX rendering to response (initial display during generation)
                try:
                    from src.utils.latex_renderer import render_with_latex
                    display_response = render_with_latex(response)
                    # Fallback if rendering produced empty output
                    if not display_response or not display_response.strip():
                         display_response = response
                except Exception:
                    display_response = response

                # CRITICAL: Append formatted references to the text for display/copying
                # Uses the standard "Cited vs Additional" logic from reference_splitter
                if apa_references:
                    try:
                        from src.utils.reference_splitter import split_references, format_split_references
                        # Use split_references logic from original script
                        cited, uncited = split_references(response, apa_references)
                        
                        formatted_refs = format_split_references(
                            cited, uncited, 
                            cited_header="\n\n## References (Cited in Response)",
                            uncited_header="\n\n### Additional Sources (Retrieved)"
                        )
                        display_response += formatted_refs
                    except ImportError:
                        pass

                st.markdown(display_response)
            
                if cfg["show_sources"]:
                    display_sources(sources, apa_references, response)  # Pass response for ref splitting
            
                # Create stable hash for this message
                import hashlib
                msg_hash = hashlib.md5(f"{prompt}_{len(st.session_state.messages)}".encode()).hexdigest()[:8]
        
                # Save to message history (UI elements rendered from history loop on next rerun)
                # Store in session with hash key (for expandable reliability)
                st.session_state[f"last_reflection_{msg_hash}"] = reflection_log_data
            
                # Add message to chat history
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response,
                    "model": cfg["model"],
                    "depth": cfg["depth"],
                    "msg_hash": msg_hash,
                    "reflection_log": reflection_log_data # Persist sequential thinking log
                })
        
                  # Finalize monitor with completion state
                unique_dois = len(set(s.get("doi", "") for s in sources if s.get("doi")))
                
                # Mark processing complete
                finish_monitor(unique_dois)
        
                # Re-enable sidebar widgets and rerun to show buttons from history loop
                st.session_state.is_processing = False
                st.rerun()


def safe_main():
    """Wrapper with error boundary for graceful error handling."""
    try:
        main()
    except Exception as e:
        logger.exception("Unexpected error in main application")
        st.error("An unexpected error occurred")
        st.code(str(e))
        if st.button("Refresh Application"):
            st.rerun()


if __name__ == "__main__":
    safe_main()
