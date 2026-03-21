"""
SME Research Assistant - Pipeline State Manager

Manages pipeline state for graceful stop-and-go operations.
Tracks phase progress and enables resume after interruption.
"""

import json
import os
import uuid
import hashlib
import tempfile
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class PhaseState:
    """State of a single pipeline phase."""
    status: str = "PENDING"  # PENDING, IN_PROGRESS, COMPLETED, FAILED
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    items_total: int = 0
    items_processed: int = 0
    items_failed: int = 0
    items_skipped: int = 0
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhaseState":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass 
class PipelineState:
    """
    Complete pipeline state for resume capability.
    
    Tracks:
    - Overall run status
    - Current phase
    - Per-phase progress
    - Graceful shutdown flag
    - Last discovery date (for incremental mode)
    """
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: str = "PENDING"  # PENDING, IN_PROGRESS, COMPLETED, FAILED
    current_phase: str = "DISCOVERY"  # DISCOVERY, DOWNLOAD, EMBEDDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    graceful_shutdown: bool = False
    config_hash: Optional[str] = None
    last_discovery_date: Optional[str] = None  # ISO date for incremental discovery
    phases: Dict[str, PhaseState] = field(default_factory=lambda: {
        "DISCOVERY": PhaseState(),
        "DOWNLOAD": PhaseState(),
        "EMBEDDING": PhaseState()
    })
    
    # Class-level state file path
    _state_file: Path = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "run_id": self.run_id,
            "status": self.status,
            "current_phase": self.current_phase,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "graceful_shutdown": self.graceful_shutdown,
            "config_hash": self.config_hash,
            "last_discovery_date": self.last_discovery_date,
            "phases": {name: phase.to_dict() for name, phase in self.phases.items()}
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineState":
        """Create from dictionary."""
        phases = {}
        for name, phase_data in data.get("phases", {}).items():
            phases[name] = PhaseState.from_dict(phase_data)
        
        return cls(
            run_id=data.get("run_id", str(uuid.uuid4())[:8]),
            status=data.get("status", "PENDING"),
            current_phase=data.get("current_phase", "DISCOVERY"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            graceful_shutdown=data.get("graceful_shutdown", False),
            config_hash=data.get("config_hash"),
            last_discovery_date=data.get("last_discovery_date"),
            phases=phases
        )
    
    def save(self, state_file: Optional[Path] = None) -> None:
        """
        Atomically save state to file.
        
        Uses write-to-temp-then-rename pattern to prevent corruption.
        """
        if state_file:
            self._state_file = Path(state_file)
        
        if not self._state_file:
            raise ValueError("State file path not set")
        
        self.updated_at = datetime.now().isoformat()
        
        # Ensure directory exists
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Write to temporary file first
        temp_fd, temp_path = tempfile.mkstemp(
            dir=self._state_file.parent,
            prefix=".pipeline_state_",
            suffix=".tmp"
        )
        
        try:
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, indent=2)
            
            # Atomic rename (works on same filesystem)
            os.replace(temp_path, self._state_file)
            logger.debug(f"State saved to {self._state_file}")
            
        except Exception as e:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            logger.error(f"Failed to save state: {e}")
            raise
    
    @classmethod
    def load(cls, state_file: Path) -> Optional["PipelineState"]:
        """
        Load state from file.
        
        Returns None if file doesn't exist or is corrupted.
        """
        state_file = Path(state_file)
        
        if not state_file.exists():
            logger.debug(f"No state file found at {state_file}")
            return None
        
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            state = cls.from_dict(data)
            state._state_file = state_file
            logger.info(f"Loaded pipeline state: run_id={state.run_id}, phase={state.current_phase}")
            return state
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Corrupted state file, starting fresh: {e}")
            return None
    
    @classmethod
    def load_or_create(cls, state_file: Path, config_hash: Optional[str] = None) -> "PipelineState":
        """Load existing state or create new one."""
        state = cls.load(state_file)
        
        if state is None:
            state = cls()
            state._state_file = state_file
            state.config_hash = config_hash
            logger.info(f"Created new pipeline state: run_id={state.run_id}")
        
        return state
    
    # =========================================================================
    # Phase Transition Methods
    # =========================================================================
    
    def start_phase(self, phase: str) -> None:
        """Mark a phase as started."""
        if phase not in self.phases:
            self.phases[phase] = PhaseState()
        
        self.current_phase = phase
        self.status = "IN_PROGRESS"
        self.phases[phase].status = "IN_PROGRESS"
        self.phases[phase].started_at = datetime.now().isoformat()
        
        logger.info(f"Phase {phase} started")
        self.save()
    
    def complete_phase(self, phase: str, stats: Optional[Dict[str, int]] = None) -> None:
        """Mark a phase as completed."""
        if phase not in self.phases:
            self.phases[phase] = PhaseState()
        
        self.phases[phase].status = "COMPLETED"
        self.phases[phase].completed_at = datetime.now().isoformat()
        
        if stats:
            self.phases[phase].items_total = stats.get("total", 0)
            self.phases[phase].items_processed = stats.get("processed", stats.get("successful", 0))
            self.phases[phase].items_failed = stats.get("failed", 0)
            self.phases[phase].items_skipped = stats.get("skipped", 0)
        
        logger.info(f"Phase {phase} completed")
        self.save()
    
    def fail_phase(self, phase: str, error: str) -> None:
        """Mark a phase as failed."""
        if phase not in self.phases:
            self.phases[phase] = PhaseState()
        
        self.phases[phase].status = "FAILED"
        self.phases[phase].error = error
        self.status = "FAILED"
        
        logger.error(f"Phase {phase} failed: {error}")
        self.save()
    
    def update_progress(self, phase: str, processed: int, total: int) -> None:
        """Update progress for a phase (for long-running phases)."""
        if phase not in self.phases:
            self.phases[phase] = PhaseState()
        
        self.phases[phase].items_processed = processed
        self.phases[phase].items_total = total
        self.save()
    
    def mark_completed(self) -> None:
        """Mark the entire pipeline as completed."""
        self.status = "COMPLETED"
        self.current_phase = "DONE"
        logger.info(f"Pipeline {self.run_id} completed successfully")
        self.save()
    
    def mark_graceful_shutdown(self) -> None:
        """Mark that we're shutting down gracefully."""
        self.graceful_shutdown = True
        logger.info("Graceful shutdown initiated")
        self.save()
    
    # =========================================================================
    # Resume Logic
    # =========================================================================
    
    def needs_resume(self) -> bool:
        """Check if this state represents an incomplete run that needs resuming."""
        return self.status == "IN_PROGRESS"
    
    def get_resume_phase(self) -> str:
        """Get the phase to resume from."""
        if self.status != "IN_PROGRESS":
            return "NONE"
        
        # Find the first incomplete phase
        for phase in ["DISCOVERY", "DOWNLOAD", "EMBEDDING"]:
            if phase not in self.phases:
                return phase
            if self.phases[phase].status in ["PENDING", "IN_PROGRESS"]:
                return phase
        
        return self.current_phase
    
    def should_skip_phase(self, phase: str) -> bool:
        """Check if a phase was already completed and should be skipped."""
        if phase not in self.phases:
            return False
        return self.phases[phase].status == "COMPLETED"


def compute_config_hash(config: Dict[str, Any]) -> str:
    """Compute a hash of the config for change detection."""
    config_str = json.dumps(config, sort_keys=True)
    return hashlib.md5(config_str.encode()).hexdigest()[:12]
