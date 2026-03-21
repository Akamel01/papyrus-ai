"""
Centralized Session State Manager.

Provides a single source of truth for all session state variables
with type hints, defaults, and helper methods.
"""

import streamlit as st
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field


@dataclass
class StateDefaults:
    """Default values for all session state keys."""
    # Authentication
    authenticated: bool = False
    
    # Chat
    messages: List[Dict] = field(default_factory=list)
    current_query: str = ""
    
    # Processing
    is_processing: bool = False
    stop_requested: bool = False
    
    # Progress Tracking
    monitor_steps: List[Dict] = field(default_factory=list)
    live_steps: List[Dict] = field(default_factory=list)
    current_main_pill: int = 0
    current_sub_pill: int = 0
    current_section: int = 0
    section_total: int = 0
    progress_config_name: str = "standard"
    
    # Query Configuration
    query_config: Dict = field(default_factory=dict)
    
    # UI placeholders
    monitor_placeholder: Any = None
    
    # Monitor panel state (NEW)
    monitor_state: str = "idle"  # "idle", "processing", "finalized"
    monitor_progress: dict = field(default_factory=lambda: {
        "total_progress": 0,
        "active_step": "",
        "steps": []
    })
    monitor_start_time: float = None
    monitor_summary: dict = field(default_factory=dict)
    _monitor_col: Any = None


class SessionManager:
    """Centralized session state management."""
    
    @staticmethod
    def init():
        """Initialize all session state variables with defaults."""
        defaults = StateDefaults()
        
        # Use dataclass fields to iterate
        for field_name in defaults.__dataclass_fields__:
            if field_name not in st.session_state:
                value = getattr(defaults, field_name)
                # Handle mutable default values
                if isinstance(value, (list, dict)):
                    st.session_state[field_name] = value.copy() if value else type(value)()
                else:
                    st.session_state[field_name] = value
    
    @staticmethod
    def reset_for_new_query():
        """Reset state for a new query."""
        st.session_state.is_processing = True
        st.session_state.stop_requested = False
        st.session_state.monitor_steps = []
        st.session_state.live_steps = []
        st.session_state.current_main_pill = 0
        st.session_state.current_sub_pill = 0
        st.session_state.current_section = 0
    
    @staticmethod
    def add_message(role: str, content: str, **metadata):
        """Add a message to chat history."""
        message = {"role": role, "content": content, **metadata}
        st.session_state.messages.append(message)
    
    @staticmethod
    def add_monitor_step(
        name: str, 
        status: str = "active", 
        duration: float = 0.0,
        detail: str = ""
    ):
        """Add a step to the monitor panel."""
        step = {
            "name": name,
            "status": status,
            "duration": duration,
            "detail": detail
        }
        st.session_state.monitor_steps.append(step)
    
    @staticmethod
    def update_last_step(status: str, duration: float):
        """Update the status and duration of the last monitor step."""
        if st.session_state.monitor_steps:
            st.session_state.monitor_steps[-1]["status"] = status
            st.session_state.monitor_steps[-1]["duration"] = duration
    
    @staticmethod
    def advance_progress():
        """Advance to the next sub-pill."""
        st.session_state.current_sub_pill += 1
    
    @staticmethod
    def advance_main_pill():
        """Advance to the next main pill and reset sub-pill."""
        st.session_state.current_main_pill += 1
        st.session_state.current_sub_pill = 0
    
    @staticmethod
    def finish_processing():
        """Mark processing as complete."""
        st.session_state.is_processing = False
        st.session_state.stop_requested = False
    
    @staticmethod
    def is_stop_requested() -> bool:
        """Check if stop was requested."""
        return st.session_state.get("stop_requested", False)
    
    @staticmethod
    def get_config() -> Dict:
        """Get current query configuration."""
        return st.session_state.get("query_config", {})
    
    @staticmethod
    def set_config(config: Dict):
        """Set query configuration."""
        st.session_state.query_config = config
