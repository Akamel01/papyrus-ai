"""
Core streaming pipeline interfaces and data structures.
"""

from abc import ABC, abstractmethod
from typing import Iterator, Any, Optional, Dict, List
from dataclasses import dataclass, field
import logging
import traceback

logger = logging.getLogger(__name__)

@dataclass
class PipelineItem:
    """
    Represents a single item flowing through the pipeline.
    Wraps the data (payload) and tracks processing status/errors.
    """
    id: str  # Unique ID (e.g. paper unique_id)
    payload: Any  # The actual data (Paper object, text chunk, etc.)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_valid(self) -> bool:
        """Returns True if no error has occurred."""
        return self.error is None
    
    def fail(self, error_msg: str):
        """Mark item as failed."""
        self.error = error_msg
        self.payload = None  # Clear payload to free memory if needed

class PipelineStage(ABC):
    """
    Abstract base class for a pipeline stage.
    """
    
    def __init__(self, name: str):
        self.name = name
    
    @abstractmethod
    def process(self, input_stream: Iterator[PipelineItem]) -> Iterator[PipelineItem]:
        """
        Process the input stream and yield results.
        Must handle exceptions gracefully to maintain stream integrity.
        """
        pass
    
    def _handle_error(self, item: PipelineItem, e: Exception) -> PipelineItem:
        """Helper to mark item as failed with exception details."""
        error_msg = f"Error in {self.name}: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        item.fail(error_msg)
        return item
