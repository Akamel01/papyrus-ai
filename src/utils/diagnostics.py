"""
Diagnostic Utility for SME Research Assistant.

Provides a robust "DiagnosticGate" context manager that wraps critical
operations. If an exception occurs, it:
1. Captures the failure details (traceback, locals).
2. Sanitizes input data to prevent UI lag.
3. Reports the failure to the Live Monitor as an expandable Diagnostic Report.
4. Optionally suppresses the exception if non-critical.
"""

import sys
import traceback
import logging
from typing import Optional, Dict, Any, Type
import json

# Import monitor components (UI integration)
# We use deferred import or direct import if safe. 
# monitor_components relies on streamlit, which is safe here.
from src.ui.monitor_components import add_warning, inject_monitor_update

logger = logging.getLogger(__name__)

class DiagnosticGate:
    """
    Context Manager to gate critical operations and report failures to the UI.
    
    Usage:
        with DiagnosticGate("Processing Section 1", severity="error", context={"inputs": inputs}):
            critical_operation()
    """
    
    def __init__(
        self, 
        name: str, 
        severity: str = "warning", 
        context: Dict[str, Any] = None, 
        remediation: str = None,
        suppress: bool = False,
        success_msg: str = None
    ):
        """
        Args:
            name: Human-readable name of the gate (e.g. "Section Verification")
            severity: "warning", "error", or "critical"
            context: Dict of relevant variables to debug the failure
            remediation: Optional suggestion for the user (appended to message)
            suppress: If True, swallows the exception (for non-critical gates)
            success_msg: Optional message to log if operation succeeds (Diagnostic Heartbeat)
        """
        self.name = name
        self.severity = severity
        self.context = context or {}
        self.remediation = remediation
        self.suppress = suppress
        self.success_msg = success_msg

    def set_success_message(self, msg: str):
        """Allow updating the success message dynamically (e.g. to include counts)."""
        self.success_msg = msg

    def __enter__(self):
        return self

    def __exit__(self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> bool:
        if exc_type is None:
            # Heartbeat: Report success if configured
            if self.success_msg:
                try:
                    # Strip detailed context from success messages to reduce noise, unless debugging
                    # We pass 'hits' or 'count' via message string usually
                    add_warning(
                        message=f"{self.name}: {self.success_msg}",
                        type="success"
                    )
                    inject_monitor_update()
                except Exception:
                    pass
            return False  # No exception, proceed normally
            
        # 1. Capture Technical Details
        trace_str = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
        error_msg = f"{self.name} Failed: {str(exc_val)}"
        
        if self.remediation:
            error_msg += f" \n(Suggestion: {self.remediation})"
            
        # 2. Sanitize Context (CRITICAL for UI Performance)
        # We truncate large values because dumping 50KB strings into Streamlit session state
        # can cause massive lag or browser crashes.
        safe_context = self._sanitize_context(self.context)
        
        # 3. Report to Live Monitor
        try:
            add_warning(
                message=error_msg,
                type=self.severity,
                details=trace_str,
                context=safe_context
            )
            # Force immediate UI update if possible
            inject_monitor_update()
            
        except Exception as e:
            # Fallback if reporting fails (don't crash the crash handler)
            logger.error(f"Failed to report diagnostic: {e}")
            
        # 4. Log to console/file as well
        logger.error(f"[Diagnostic] {error_msg}\n{trace_str}")
        
        # 5. Return True checks if we should swallow the exception
        return self.suppress

    def _sanitize_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Truncate large values in the context dict."""
        MAX_STR_LEN = 1000  # Truncate strings longer than this
        MAX_LIST_LEN = 10   # Only show first 10 items of list
        
        sanitized = {}
        try:
            for key, val in context.items():
                if isinstance(val, str):
                    if len(val) > MAX_STR_LEN:
                        sanitized[key] = val[:MAX_STR_LEN] + f"... [TRUNCATED {len(val)-MAX_STR_LEN} chars]"
                    else:
                        sanitized[key] = val
                elif isinstance(val, (list, tuple)):
                    if len(val) > MAX_LIST_LEN:
                        sanitized[key] = [str(v)[:100] for v in val[:MAX_LIST_LEN]] + [f"... {len(val)-MAX_LIST_LEN} more items"]
                    else:
                        sanitized[key] = [str(v)[:100] for v in val] # stringify items to be safe
                elif isinstance(val, (dict)):
                     # Shallow recursion for dicts
                     if len(str(val)) > MAX_STR_LEN:
                         sanitized[key] = str(val)[:MAX_STR_LEN] + "..."
                     else:
                         sanitized[key] = val
                else:
                    sanitized[key] = str(val) # Default to string representation
        except Exception as e:
            sanitized["_sanitization_error"] = str(e)
            
        return sanitized


def report_diagnostic(message: str, error: Exception = None, context: Dict = None, severity: str = "warning"):
    """Helper to report a diagnostic without a context manager."""
    details = "".join(traceback.format_exception(type(error), error, error.__traceback__)) if error else None
    
    # Use temporary gate just for sanitization logic
    gate = DiagnosticGate("Manual Report", severity, context)
    safe_context = gate._sanitize_context(context or {})
    
    add_warning(message, type=severity, details=details, context=safe_context)
    inject_monitor_update()
