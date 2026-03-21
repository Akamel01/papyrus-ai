"""
Latency Tracing for RAG Pipeline.

Provides timing waterfall for debugging slow queries and identifying bottlenecks.
"""

import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@dataclass
class TimingSpan:
    """A single timing span in the trace."""
    name: str
    start_time: float
    end_time: float = 0.0
    
    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000


@dataclass
class LatencyTrace:
    """Complete latency trace for a query."""
    query: str
    spans: List[TimingSpan] = field(default_factory=list)
    total_start: float = 0.0
    total_end: float = 0.0
    
    def add_span(self, span: TimingSpan):
        self.spans.append(span)
    
    @property
    def total_duration_ms(self) -> float:
        return (self.total_end - self.total_start) * 1000
    
    def to_waterfall(self) -> str:
        """Generate ASCII waterfall chart."""
        if not self.spans:
            return "No spans recorded"
        
        lines = ["=" * 60]
        lines.append(f"Query: {self.query[:50]}...")
        lines.append(f"Total: {self.total_duration_ms:.0f}ms")
        lines.append("=" * 60)
        
        max_name_len = max(len(s.name) for s in self.spans)
        max_duration = max(s.duration_ms for s in self.spans) if self.spans else 1
        bar_width = 30
        
        for span in self.spans:
            bar_len = int((span.duration_ms / max_duration) * bar_width)
            bar = "█" * bar_len + "░" * (bar_width - bar_len)
            pct = (span.duration_ms / self.total_duration_ms) * 100 if self.total_duration_ms > 0 else 0
            lines.append(
                f"{span.name:<{max_name_len}} [{bar}] {span.duration_ms:>6.0f}ms ({pct:>4.1f}%)"
            )
        
        lines.append("=" * 60)
        return "\n".join(lines)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging."""
        return {
            "query": self.query,
            "total_ms": self.total_duration_ms,
            "spans": [
                {"name": s.name, "duration_ms": s.duration_ms}
                for s in self.spans
            ]
        }


class LatencyTracer:
    """Context manager for tracing latency."""
    
    def __init__(self, query: str):
        self.trace = LatencyTrace(query=query)
        self._current_span: Optional[TimingSpan] = None
    
    def __enter__(self):
        self.trace.total_start = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.trace.total_end = time.perf_counter()
        logger.info(f"Query completed in {self.trace.total_duration_ms:.0f}ms")
        return False
    
    @contextmanager
    def span(self, name: str):
        """Time a specific operation."""
        span = TimingSpan(name=name, start_time=time.perf_counter())
        try:
            yield span
        finally:
            span.end_time = time.perf_counter()
            self.trace.add_span(span)
            logger.debug(f"[{name}] {span.duration_ms:.0f}ms")
    
    def get_waterfall(self) -> str:
        return self.trace.to_waterfall()
    
    def get_bottleneck(self) -> Optional[str]:
        """Identify the slowest operation."""
        if not self.trace.spans:
            return None
        slowest = max(self.trace.spans, key=lambda s: s.duration_ms)
        return f"{slowest.name}: {slowest.duration_ms:.0f}ms"


def create_tracer(query: str) -> LatencyTracer:
    """Factory function to create a latency tracer."""
    return LatencyTracer(query)
