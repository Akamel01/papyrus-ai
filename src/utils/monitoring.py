"""
SME Research Assistant - Monitoring Module

Provides thread-safe, structured logging for RAG pipeline execution.
Tracks nested steps, latency, inputs/outputs, and error stacks.
"""

import time
import json
import uuid
import logging
import traceback
import contextvars
from datetime import datetime
from typing import Optional, Any, Dict, List, Union
from pathlib import Path

logger = logging.getLogger(__name__)

# Thread-local storage for the current run context
# Ensures multiple users in Streamlit don't overwrite each other's logs
_run_context = contextvars.ContextVar("run_context", default=None)


class RunContext:
    """
    Manages the global state for a single execution run.
    Stores metadata and the flat list of steps for serialization.
    """
    def __init__(self, query: str = "", config: Dict = None):
        self.run_id = str(uuid.uuid4())
        self.start_time = datetime.now().isoformat()
        self.query = query
        self.config = config or {}
        self.steps: List[Dict] = []
        self._active_trackers = []  # Stack to track nesting
        self.on_step_complete: Optional[callable] = None  # Live monitoring callback

    @classmethod
    def get_current(cls) -> Optional['RunContext']:
        """Get the active RunContext for this thread, if any."""
        return _run_context.get()

    @classmethod
    def start_new_run(cls, query: str = "", config: Dict = None) -> 'RunContext':
        """Initialize a new RunContext and set it as active."""
        ctx = cls(query, config)
        _run_context.set(ctx)
        return ctx

    def add_step_record(self, step_data: Dict):
        """Append a completed step record to the log and invoke callback."""
        self.steps.append(step_data)
        
        # Invoke live monitoring callback if registered
        if self.on_step_complete:
            try:
                self.on_step_complete(step_data)
            except Exception as e:
                logger.warning(f"Step callback error: {e}")
    
    def set_callback(self, callback: callable):
        """Register a callback for live step updates."""
        self.on_step_complete = callback

    def save_logs(self):
        """Write the run data to disk."""
        try:
            log_dir = Path("logs/runs") / datetime.now().strftime("%Y-%m-%d")
            log_dir.mkdir(parents=True, exist_ok=True)
            
            filename = log_dir / f"run_{self.run_id}.json"
            
            data = {
                "run_id": self.run_id,
                "timestamp": self.start_time,
                "query": self.query,
                "config": self.config,
                "total_steps": len(self.steps),
                "steps": self.steps
            }
            
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
            logger.info(f"Run logs saved to {filename}")
            
        except Exception as e:
            logger.error(f"Failed to save run logs: {e}")


class StepTracker:
    """
    Context manager to track a specific workflow step.
    Handles timing, error capture, and logging.
    """
    def __init__(self, name: str, parent_context: Optional[RunContext] = None):
        self.name = name
        self.ctx = parent_context or RunContext.get_current()
        self.start_time = 0
        self.inputs = {}
        self.outputs = {}
        self.metadata = {}
        
    def __enter__(self):
        self.start_time = time.time()
        if self.ctx:
            # Add self to active stack to track nesting (future feature)
            self.ctx._active_trackers.append(self.name)
        
        logger.debug(f"Starting step: {self.name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        status = "failed" if exc_type else "success"
        
        error_info = None
        if exc_type:
            error_info = {
                "type": str(exc_type.__name__),
                "message": str(exc_val),
                "traceback": "".join(traceback.format_tb(exc_tb))
            }
            logger.error(f"Step '{self.name}' failed: {exc_val}")
        
        step_record = {
            "name": self.name,
            "status": status,
            "duration_seconds": round(duration, 3),
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            "inputs": self._sanitize(self.inputs),
            "outputs": self._sanitize(self.outputs),
            "metadata": self.metadata,
            "nests": self.ctx._active_trackers[:-1] if self.ctx else []
        }
        
        if error_info:
            step_record["error"] = error_info
            
        if self.ctx:
            self.ctx.add_step_record(step_record)
            self.ctx._active_trackers.pop()
            
        logger.debug(f"Finished step: {self.name} ({status}, {duration:.2f}s)")
        
        # Propagate exception - monitoring should not swallow errors
        return False

    def log_input(self, key: str, value: Any):
        """Log an input parameter."""
        self.inputs[key] = value

    def log_output(self, key: str, value: Any):
        """Log an output result."""
        self.outputs[key] = value

    def log_metadata(self, key: str, value: Any):
        """Log metadata (stats, counts, etc)."""
        self.metadata[key] = value

    def _sanitize(self, data: Any) -> Any:
        """Prevent massive logs by truncating large strings."""
        MAX_LEN = 20000  # 20KB limit per field
        
        if isinstance(data, str):
            if len(data) > MAX_LEN:
                return data[:MAX_LEN] + f"... [TRUNCATED {len(data)-MAX_LEN} chars]"
            return data
            
        if isinstance(data, dict):
            return {k: self._sanitize(v) for k, v in data.items()}
            
        if isinstance(data, list):
            # Only sanitize first 50 items if list is huge
            if len(data) > 100:
                return [self._sanitize(v) for v in data[:50]] + [f"... {len(data)-50} more items"]
            return [self._sanitize(v) for v in data]
            
        return data


def start_run(query: str, config: Dict = None) -> RunContext:
    """Helper to start a run."""
    return RunContext.start_new_run(query, config)

def end_run():
    """Helper to save logs at end of run."""
    ctx = RunContext.get_current()
    if ctx:
        ctx.save_logs()
