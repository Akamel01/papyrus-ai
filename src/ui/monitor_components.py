"""
Live Monitor Panel Components.

Provides real-time processing status display with:
- Three stages: IDLE, PROCESSING, COMPLETE
- Step tracking with automatic completion
- Live elapsed timer (JavaScript-based)
- Progress bar calculation
- Collapsible warnings section

Architecture:
- State-only API functions (no rendering inside)
- Single render_monitor() function called once per cycle
- JavaScript DOM updates for real-time changes during processing

Usage:
    from src.ui.monitor_components import (
        init_monitor,        # Initialize state (once at page load)
        start_monitor,       # Reset to processing state
        add_step,            # Add new step (auto-completes previous)
        complete_step,       # Manually complete current step
        add_warning,         # Add warning message
        finish_monitor,      # Set complete state
        render_monitor,      # Get HTML for current state
        inject_monitor_update,  # Get JS script to update DOM
    )
"""

from dataclasses import dataclass, field
from typing import List, Optional
import streamlit as st
import time
import html
import textwrap


# ============================================================================
# CONSTANTS
# ============================================================================

TIMER_UPDATE_INTERVAL_MS = 100

# Session state keys
STATE_KEY = "monitor_state"           # "idle", "processing", "complete"
STEPS_KEY = "monitor_steps"           # List[MonitorStep]
WARNINGS_KEY = "monitor_warnings"     # List[Dict] (Legacy: List[str])
START_TIME_KEY = "monitor_start_time" # float (timestamp)
SOURCES_KEY = "monitor_sources"       # int
TOTAL_STEPS_KEY = "monitor_total_steps" # int


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class MonitorStep:
    """Represents a processing step."""
    name: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    
    @property
    def duration_seconds(self) -> float:
        """Get step duration in seconds."""
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time
    
    @property
    def duration_str(self) -> str:
        # User Request: "working for times over 60s but showing (00m 5.2s) for <60s"
        # Logic: If < 60s, show "5.2s". If >= 60s, show "01m 05.2s"
        secs = self.duration_seconds
        
        if secs < 60:
            return f"{secs:.1f}s"
        else:
            mins = int(secs // 60)
            secs_remainder = secs % 60
            return f"{mins:02d}m {secs_remainder:.1f}s"
    
    @property
    def is_complete(self) -> bool:
        """Check if step is complete."""
        return self.end_time is not None


# ============================================================================
# STATE MANAGEMENT (Private)
# ============================================================================

def _get_session_state():
    """Get Streamlit session state. Import here to avoid circular imports."""
    import streamlit as st
    return st.session_state


def _init_defaults() -> None:
    """Initialize default state values if not present."""
    state = _get_session_state()
    
    if STATE_KEY not in state:
        state[STATE_KEY] = "idle"
    if STEPS_KEY not in state:
        state[STEPS_KEY] = []
    if WARNINGS_KEY not in state:
        state[WARNINGS_KEY] = []
    if START_TIME_KEY not in state:
        state[START_TIME_KEY] = 0.0
    if SOURCES_KEY not in state:
        state[SOURCES_KEY] = 0
    if TOTAL_STEPS_KEY not in state:
        state[TOTAL_STEPS_KEY] = 5


def _get_state() -> str:
    """Get current monitor state."""
    _init_defaults()
    return _get_session_state()[STATE_KEY]


def _get_steps() -> List[MonitorStep]:
    """Get list of steps."""
    _init_defaults()
    return _get_session_state()[STEPS_KEY]


def _get_warnings() -> List[str]:
    """Get list of warnings."""
    _init_defaults()
    return _get_session_state()[WARNINGS_KEY]


def _get_start_time() -> float:
    """Get processing start time."""
    _init_defaults()
    return _get_session_state()[START_TIME_KEY]


def _get_sources() -> int:
    """Get source count."""
    _init_defaults()
    return _get_session_state()[SOURCES_KEY]


def _calculate_progress() -> int:
    """
    Calculate progress percentage based on steps.
    
    Returns value between 0-95 (never 100 during processing).
    """
    steps = _get_steps()
    if not steps:
        return 0
    
    state = _get_session_state()
    total_expected_steps = state.get(TOTAL_STEPS_KEY, len(steps))
    completed = sum(1 for s in steps if s.is_complete)
    
    try:
        # Add partial credit for current step
        if completed < total_expected_steps:
            completed += 0.5
            
        # Cap at 95% (100% only shown in COMPLETE state)
        return min(95, int((completed / total_expected_steps) * 100))
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Dynamic progress calculation failed: {e}. Falling back to simple step count.")
        
        # Fallback to legacy length-based calculation
        total_fallback = max(len(steps), 1)
        completed_fallback = sum(1 for s in steps if s.is_complete)
        if completed_fallback < total_fallback:
            completed_fallback += 0.5
        return min(95, int((completed_fallback / total_fallback) * 100))


# ============================================================================
# PUBLIC API - STATE ONLY (No Rendering)
# ============================================================================

def init_monitor() -> None:
    """
    Initialize monitor state.
    
    Call once at page load. Only initializes defaults if not present.
    Creates the placeholder for the monitor.
    """
    _init_defaults()
    
    # Always create a fresh placeholder at the current location
    # This ensures the placeholder object is valid for the current run
    st.session_state.monitor_placeholder = st.empty()
    
    # Render initial state
    _render_monitor(include_script=True)


def start_monitor(total_expected_steps: int = 5) -> None:
    """
    Reset to processing state for new query.
    
    Clears all previous steps and warnings, resets timer.
    Does NOT render anything.
    """
    state = _get_session_state()
    state[STATE_KEY] = "processing"
    state[STEPS_KEY] = []  # Critical: Clear steps!
    state[WARNINGS_KEY] = []
    state[START_TIME_KEY] = time.time()
    state[SOURCES_KEY] = 0
    state[TOTAL_STEPS_KEY] = total_expected_steps

def set_total_steps(total_steps: int) -> None:
    """
    Dynamically update the expected total steps.
    Used for sequential/section mode when outline size is revealed.
    """
    state = _get_session_state()
    state[TOTAL_STEPS_KEY] = total_steps


def add_step(name: str) -> None:
    """
    Add a new processing step.
    
    Automatically completes the previous step if one exists.
    Does NOT render anything.
    
    Args:
        name: Step name (e.g., "Analyzing Query", "Searching 50 papers")
    """
    state = _get_session_state()
    steps = state.get(STEPS_KEY, [])
    
    # Auto-complete previous step
    if steps and not steps[-1].is_complete:
        steps[-1].end_time = time.time()
    
    # Add new step
    new_step = MonitorStep(name=name, start_time=time.time())
    steps.append(new_step)
    state[STEPS_KEY] = steps


def complete_step() -> None:
    """
    Manually complete the current step.
    
    Does NOT render anything.
    """
    state = _get_session_state()
    steps = state.get(STEPS_KEY, [])
    
    if steps and not steps[-1].is_complete:
        steps[-1].end_time = time.time()


def add_warning(message: str, type: str = "warning", details: str = None, context: dict = None) -> None:
    """
    Add a warning or error message with optional details.
    
    Args:
        message: Main warning text
        type: "warning", "error", or "critical"
        details: Technical details or traceback (for expandable view)
        context: Dictionary of relevant variables for debugging
    """
    state = _get_session_state()
    warnings = state.get(WARNINGS_KEY, [])
    
    # Create structured warning object
    warning_obj = {
        "message": message,
        "type": type,
        "details": details,
        "context": context,
        "timestamp": time.time()
    }
    
    warnings.append(warning_obj)
    state[WARNINGS_KEY] = warnings


def finish_monitor(sources_count: int = 0) -> None:
    """
    Complete processing and set final state.
    
    Completes any remaining step, sets state to "complete".
    Does NOT render anything.
    
    Args:
        sources_count: Number of sources used in response
    """
    state = _get_session_state()
    
    # Complete last step
    steps = state.get(STEPS_KEY, [])
    if steps and not steps[-1].is_complete:
        steps[-1].end_time = time.time()
    
    state[STATE_KEY] = "complete"
    state[SOURCES_KEY] = sources_count


# ============================================================================
# PUBLIC API - RENDERING
# ============================================================================

def _render_monitor(include_script: bool = True) -> None:
    """Render the monitor panel to the placeholder."""
    html_content = _get_monitor_html(include_script)
    
    # Use placeholder if available for updates
    placeholder = st.session_state.get("monitor_placeholder")
    if placeholder:
        placeholder.markdown(html_content, unsafe_allow_html=True)
    else:
        # Fallback for initial render if placeholder missing (shouldn't happen if init_monitor called)
        st.markdown(html_content, unsafe_allow_html=True)


def _get_monitor_html(include_script: bool = True) -> str:
    """
    Generate HTML for the monitor panel based on current state.
    """
    current_state = _get_state()
    
    html_content = ""
    if current_state == "processing":
        html_content = _render_processing_state(include_script=include_script)
    elif current_state == "complete":
        html_content = _render_complete_state()
    else:
        html_content = _render_idle_state()
        
    # CRITICAL FIX: Strip newlines (replacing with SPACE for safety) to prevent 
    # Markdown from interpreting indented HTML tags as Code Blocks.
    return html_content.replace('\n', ' ').strip()


def render_monitor(include_script: bool = True) -> str:
    """Legacy public API - returns HTML string."""
    return _get_monitor_html(include_script)


def inject_monitor_update() -> str:
    """
    Update the monitor using Streamlit's native placeholder.
    
    This replaces the fragile JS injection hack.
    """
    # Simply re-render the monitor to the existing placeholder
    _render_monitor(include_script=True)
    
    # Return empty string so st.markdown doesn't render anything extra
    return ""


# ============================================================================
# TEMPLATE GENERATORS (Private)
# ============================================================================

def _render_idle_state() -> str:
    """Generate HTML for IDLE state."""
    warnings_html = _render_warnings_section()
    
    return textwrap.dedent(f'''
    <div id="live-monitor-panel">
        <div class="monitor-header">
            <span class="monitor-title">
                <span class="monitor-title-icon">\u26A1</span>
                LIVE MONITOR
            </span>
            <span class="monitor-status-badge idle">READY</span>
        </div>
        <div class="monitor-idle-content">
            <div class="monitor-idle-icon">
                <svg width="35" height="35" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
            </div>
            <div class="monitor-idle-text">Systems Online</div>
        </div>
        {warnings_html}
    </div>
    ''')


def _render_warnings_section() -> str:
    """Render warnings section if warnings exist."""
    warnings = _get_warnings()
    if not warnings:
        return ""
    
    warnings_html = ""
    for w in warnings:
        w_escaped = html.escape(w)
        warnings_html += f'<div class="monitor-warning-item">\u26A0\uFE0F {w_escaped}</div>'
    
    return textwrap.dedent(f'''
    <div class="monitor-warnings">
        <div class="monitor-warnings-header">Warnings & Errors ({len(warnings)})</div>
        <div class="monitor-warnings-list">
            {warnings_html}
        </div>
    </div>
    ''')


def _render_processing_state(include_script: bool = True) -> str:
    """Generate HTML for PROCESSING state with timer script."""
    steps = _get_steps()
    progress = _calculate_progress()
    start_time_ms = int(_get_start_time() * 1000)
    
    # Logic Fix: Timer should track CURRENT STEP duration, not total duration
    step_start_ms = start_time_ms # fallback
    current_step = steps[-1] if steps else None
    if current_step and not current_step.is_complete:
        step_start_ms = int(current_step.start_time * 1000)
    
    # Build steps HTML
    steps_html = ""
    for i, step in enumerate(steps):
        is_current = not step.is_complete
        steps_html += _render_step(step, is_current)
    
    # If no steps yet, show placeholder
    if not steps_html:
        steps_html = '''
        <div class="monitor-step current">
            <div class="monitor-step-header">
                <span class="monitor-step-icon active">\U0001F504</span>
                <span class="monitor-step-name">Initializing...</span>
            </div>
        </div>
        '''
    
    warnings_html = _render_warnings_section()
    
    
    return textwrap.dedent(f'''
    <div id="live-monitor-panel">
        <div class="monitor-header">
            <span class="monitor-title">
                <span class="monitor-title-icon">\u26A1</span>
                LIVE MONITOR
            </span>
            <span class="monitor-status-badge processing">PROCESSING</span>
        </div>
        <div class="monitor-progress-container">
            <div class="monitor-progress-header">
                <span class="monitor-progress-label">Progress</span>
                <span class="monitor-progress-value">{progress}%</span>
            </div>
            <div class="monitor-progress-bar">
                <div class="monitor-progress-fill" style="width: {progress}%;"></div>
            </div>
        </div>
        <div class="monitor-step-history">
            {steps_html}
        </div>
        {warnings_html}
    </div>
    ''')



def _render_step(step: MonitorStep, is_current: bool) -> str:
    """Generate HTML for a single step."""
    status_class = "current" if is_current else "complete"
    icon = "\U0001F504" if is_current else "\u2713"
    icon_class = "active" if is_current else "success"
    
    duration_html = ""
    if step.end_time: # Complete
        # Use centralized formatting property
        duration_html = f'<span class="monitor-step-duration">({step.duration_str})</span>'
    elif is_current: # Running
        # Python keeps time updated on every re-render
        current_elapsed = time.time() - step.start_time
        
        # Placeholder for JS timer (but initialized with current true time)
        # Custom Style: Orange + Smaller Font
        # Using #FF9800 (Material Orange 500) for better visibility than plain 'orange'
        # style = "color: #FF9800; font-size: 0.85em; font-family: monospace; font-weight: 600;"
        # duration_html = f'<div class="monitor-step-live-timer" style="{style}">Elapsed: <span id="monitor-elapsed-timer">{current_elapsed:.1f}s</span></div>'
        
        # User explicitly requested to remove the live timer
        duration_html = ""
        
    name_escaped = html.escape(step.name)
    
    return f'''
<div class="monitor-step {status_class}">
<div class="monitor-step-header">
<span class="monitor-step-icon {icon_class}">{icon}</span>
<span class="monitor-step-name">{name_escaped}</span>
{duration_html if not is_current else ""}
</div>
{duration_html if is_current else ""}
</div>
'''


def _render_complete_state() -> str:
    """Generate HTML for COMPLETE state."""
    steps = _get_steps()
    start_time = _get_start_time()
    total_time = time.time() - start_time
    sources = _get_sources()
    
    steps_html = ""
    for step in steps:
        steps_html += _render_step(step, is_current=False)
        
    warnings_html = _render_warnings_section()
    
    # Format total time consistent with steps
    if total_time < 60:
        total_time_str = f"{total_time:.1f}s"
    else:
        mins = int(total_time // 60)
        secs_remainder = total_time % 60
        total_time_str = f"{mins:02d}m {secs_remainder:.1f}s"
    
    return textwrap.dedent(f'''
    <div id="live-monitor-panel">
        <div class="monitor-header">
            <span class="monitor-title">
                <span class="monitor-title-icon">\u26A1</span>
                LIVE MONITOR
            </span>
            <span class="monitor-status-badge complete">COMPLETE</span>
        </div>
        <div class="monitor-complete-summary">
            <div class="monitor-complete-icon">\u2713</div>
            <div class="monitor-complete-text">Analysis Complete</div>
            <div class="monitor-complete-stats" style="color: #FF9800; font-family: monospace; font-weight: 600;">
                {total_time_str} • {sources} papers
            </div>
        </div>
        <div class="monitor-step-history">
            {steps_html}
        </div>
        {warnings_html}
    </div>
    ''')





def _render_warnings_section() -> str:
    """Render expandable warnings section with detailed diagnostics."""
    warnings = _get_warnings()
    count = len(warnings)
    count_class = "zero" if count == 0 else ""
    
    warnings_list_html = ""
    for warn in warnings:
        # Handle legacy string format
        if isinstance(warn, str):
            is_error = warn.lower().startswith("error") or "failed" in warn.lower()
            warn_obj = {
                "message": warn, 
                "type": "error" if is_error else "warning",
                "details": None
            }
        else:
            warn_obj = warn
            
        # Determine styling
        w_type = warn_obj.get("type", "warning").lower()
        
        # Icon & Class Mapping
        if w_type in ["error", "critical"]:
            icon_class = "error"
            icon = "\u274C" # X Mark
        elif w_type == "success":
            icon_class = "success"
            icon = "\u2705" # Check Mark
        elif w_type == "info":
            icon_class = "info"
            icon = "\u2139\uFE0F" # Info I
        else: # warning/default
            icon_class = "warning"
            icon = "\u26A0\uFE0F" # Caution
        
        msg_escaped = html.escape(warn_obj.get("message", "Unknown"))
        details = warn_obj.get("details")
        context = warn_obj.get("context")
        
        # Build Context HTML if present
        context_html = ""
        if context:
            import json
            try:
                # Pretty print context JSON
                ctx_str = json.dumps(context, indent=2)
                ctx_escaped = html.escape(ctx_str)
                context_html = f'<div class="monitor-diagnostic-context"><strong>Context:</strong><pre>{ctx_escaped}</pre></div>'
            except:
                context_html = '<div class="monitor-diagnostic-context">Context serialization failed</div>'

        # Render Item
        if details or context:
            # Expandable Version
            details_escaped = html.escape(details) if details else ""
            warnings_list_html += f'''
            <div class="monitor-warning-item expandable {icon_class}">
                <details>
                    <summary>
                        <span class="monitor-warning-icon {icon_class}">{icon}</span>
                        <span class="monitor-warning-text">{msg_escaped}</span>
                    </summary>
                    <div class="monitor-diagnostic-details">
                        {('<pre class="monitor-traceback">' + details_escaped + '</pre>') if details else ''}
                        {context_html}
                    </div>
                </details>
            </div>
            '''
        else:
            # Simple Version
            warnings_list_html += f'''
            <div class="monitor-warning-item">
                <span class="monitor-warning-icon {icon_class}">{icon}</span>
                <span class="monitor-warning-text">{msg_escaped}</span>
            </div>
            '''
    
    # Custom CSS for expandable diagnostics
    css = """
    <style>
        .monitor-warning-item details > summary {
            cursor: pointer;
            list-style: none; /* Hide default triangle */
        }
        .monitor-warning-item details > summary::-webkit-details-marker {
            display: none;
        }
        .monitor-diagnostic-details {
            margin-top: 8px;
            padding: 8px;
            background: #1a1a1a;
            border-radius: 4px;
            border-left: 2px solid #555;
            font-size: 0.85em;
            color: #ddd;
            overflow-x: auto;
        }
        .monitor-traceback {
            color: #ff8a80; /* Light red */
            white-space: pre-wrap;
            margin: 0 0 8px 0;
            font-family: monospace;
        }
        
        /* Message Types */
        .monitor-warning-icon.success { color: #66bb6a; } /* Green */
        .monitor-warning-icon.info { color: #29b6f6; } /* Light Blue */
        .monitor-warning-icon.error { color: #ef5350; } /* Red */
        .monitor-warning-icon.warning { color: #ffa726; } /* Orange */
        
        .monitor-diagnostic-context pre {
            color: #81d4fa; /* Light blue */
            margin: 0;
            white-space: pre-wrap;
        }
        .monitor-diagnostic-context pre {
            color: #81d4fa; /* Light blue */
            margin: 0;
            white-space: pre-wrap;
        }
    </style>
    """
    
    has_critical = any(w.get("type", "warning") in ["error", "critical"] for w in warnings)
    checked_attr = "checked" if has_critical else ""
    
    return f'''
    {css}
    <div class="monitor-warnings">
        <input type="checkbox" id="warnings-toggle" class="monitor-warnings-toggle" {checked_attr}>
        <label for="warnings-toggle" class="monitor-warnings-header">
            <span class="monitor-warnings-title">
                Diagnostic Center
                <span class="monitor-warnings-count {count_class}">({count})</span>
            </span>
            <span class="monitor-warnings-arrow">▼</span>
        </label>
        <div class="monitor-warnings-content">
            <div class="monitor-warnings-list">
                {warnings_list_html if warnings_list_html else '<div style="color:#6b7280;font-size:11px;padding:8px 0;">System Healthy</div>'}
            </div>
        </div>
    </div>
    '''
