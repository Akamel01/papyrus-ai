"""
SME Research Assistant - Pipeline Monitoring System

Enterprise-level monitoring for the Autonomous Embedding Update Pipeline.
Tracks 50+ metrics across health, performance, resources, and business KPIs.
"""

import json
import os
import time
import threading
import psutil
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class PipelinePhase(str, Enum):
    """Pipeline phases."""
    IDLE = "IDLE"
    DISCOVERY = "DISCOVERY"
    DOWNLOAD = "DOWNLOAD"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    COMPLETED = "COMPLETED"


class PipelineStatus(str, Enum):
    """Pipeline status."""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class DiscoveryMetrics:
    """Metrics for the Discovery phase."""
    papers_discovered: int = 0
    papers_by_source: Dict[str, int] = field(default_factory=lambda: {
        "openalex": 0, "semantic_scholar": 0, "arxiv": 0
    })
    api_requests: int = 0
    api_errors: int = 0
    api_errors_by_type: Dict[str, int] = field(default_factory=dict)
    duplicates_removed: int = 0
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DownloadMetrics:
    """Metrics for the Download phase."""
    total_attempted: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    bytes_downloaded: int = 0
    downloads_per_minute: float = 0.0
    failures_by_reason: Dict[str, int] = field(default_factory=dict)
    retry_count: int = 0
    unpaywall_attempts: int = 0
    unpaywall_successes: int = 0
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChunkingMetrics:
    """Metrics for the Chunking phase."""
    pdfs_processed: int = 0
    pdfs_failed: int = 0
    chunks_created: int = 0
    batches_saved: int = 0
    chunks_per_pdf_avg: float = 0.0
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EmbeddingMetrics:
    """Metrics for the Embedding phase."""
    pdfs_processed: int = 0
    pdfs_failed: int = 0
    pdfs_total: int = 0
    chunks_created: int = 0
    chunks_embedded: int = 0
    chunks_per_pdf_avg: float = 0.0
    embeddings_per_second: float = 0.0
    qdrant_upserts: int = 0
    qdrant_errors: int = 0
    parse_errors: int = 0
    chunk_errors: int = 0
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResourceMetrics:
    """System resource metrics."""
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_percent: float = 0.0
    gpu_utilization: Optional[float] = None
    gpu_memory_mb: Optional[float] = None
    gpu_memory_percent: Optional[float] = None
    disk_used_gb: float = 0.0
    disk_free_gb: float = 0.0
    disk_percent: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Alert:
    """Alert record."""
    alert_type: str
    severity: str
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved: bool = False
    resolved_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineMetrics:
    """Complete metrics for a pipeline run."""
    run_id: str
    status: str = PipelineStatus.IDLE.value
    current_phase: str = PipelinePhase.IDLE.value
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: Optional[str] = None
    last_heartbeat: str = field(default_factory=lambda: datetime.now().isoformat())
    uptime_seconds: float = 0.0
    graceful_shutdown: bool = True
    
    # Phase metrics
    discovery: DiscoveryMetrics = field(default_factory=DiscoveryMetrics)
    download: DownloadMetrics = field(default_factory=DownloadMetrics)
    chunking: ChunkingMetrics = field(default_factory=ChunkingMetrics)
    embedding: EmbeddingMetrics = field(default_factory=EmbeddingMetrics)
    
    # Resource snapshots
    resources: ResourceMetrics = field(default_factory=ResourceMetrics)
    resource_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Alerts
    alerts: List[Dict[str, Any]] = field(default_factory=list)
    
    # Cumulative totals
    total_papers_in_db: int = 0
    total_embeddings: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "current_phase": self.current_phase,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "last_heartbeat": self.last_heartbeat,
            "uptime_seconds": self.uptime_seconds,
            "graceful_shutdown": self.graceful_shutdown,
            "discovery": self.discovery.to_dict(),
            "download": self.download.to_dict(),
            "chunking": self.chunking.to_dict(),
            "embedding": self.embedding.to_dict(),
            "resources": self.resources.to_dict(),
            "resource_history": self.resource_history[-10:],  # Last 10 snapshots
            "alerts": self.alerts,
            "total_papers_in_db": self.total_papers_in_db,
            "total_embeddings": self.total_embeddings
        }


class AlertManager:
    """Manages alert thresholds and triggering."""
    
    DEFAULT_THRESHOLDS = {
        "stuck_threshold_seconds": 300,
        "failure_rate_threshold": 0.20,
        "disk_free_threshold_gb": 10,
        "gpu_memory_threshold_percent": 90,
        "low_throughput_threshold": 0.5,
    }
    
    def __init__(self, thresholds: Optional[Dict[str, Any]] = None):
        self.thresholds = {**self.DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.active_alerts: Dict[str, Alert] = {}
    
    def check_alerts(self, metrics: PipelineMetrics) -> List[Alert]:
        """Check all alert conditions and return new alerts."""
        new_alerts = []
        
        # Check disk space
        if metrics.resources.disk_free_gb < self.thresholds["disk_free_threshold_gb"]:
            alert = self._create_alert(
                "disk_space_low",
                AlertSeverity.CRITICAL,
                f"Disk space critically low: {metrics.resources.disk_free_gb:.1f} GB free"
            )
            if alert:
                new_alerts.append(alert)
        else:
            self._resolve_alert("disk_space_low")
        
        # Check GPU memory
        if metrics.resources.gpu_memory_percent is not None:
            if metrics.resources.gpu_memory_percent > self.thresholds["gpu_memory_threshold_percent"]:
                alert = self._create_alert(
                    "gpu_memory_high",
                    AlertSeverity.WARNING,
                    f"GPU memory high: {metrics.resources.gpu_memory_percent:.1f}%"
                )
                if alert:
                    new_alerts.append(alert)
            else:
                self._resolve_alert("gpu_memory_high")
        
        # Check failure rate (download phase)
        if metrics.download.total_attempted > 0:
            failure_rate = metrics.download.failed / metrics.download.total_attempted
            if failure_rate > self.thresholds["failure_rate_threshold"]:
                alert = self._create_alert(
                    "high_failure_rate",
                    AlertSeverity.WARNING,
                    f"Download failure rate high: {failure_rate:.1%}"
                )
                if alert:
                    new_alerts.append(alert)
            else:
                self._resolve_alert("high_failure_rate")
        
        # Check for stuck pipeline
        try:
            last_heartbeat = datetime.fromisoformat(metrics.last_heartbeat)
            seconds_since_heartbeat = (datetime.now() - last_heartbeat).total_seconds()
            if seconds_since_heartbeat > self.thresholds["stuck_threshold_seconds"]:
                if metrics.status == PipelineStatus.RUNNING.value:
                    alert = self._create_alert(
                        "pipeline_stuck",
                        AlertSeverity.CRITICAL,
                        f"Pipeline appears stuck: no activity for {seconds_since_heartbeat:.0f}s"
                    )
                    if alert:
                        new_alerts.append(alert)
            else:
                self._resolve_alert("pipeline_stuck")
        except (ValueError, TypeError):
            pass
        
        return new_alerts
    
    def _create_alert(self, alert_type: str, severity: AlertSeverity, message: str) -> Optional[Alert]:
        """Create alert if not already active."""
        if alert_type in self.active_alerts and not self.active_alerts[alert_type].resolved:
            return None  # Already active
        
        alert = Alert(
            alert_type=alert_type,
            severity=severity.value,
            message=message
        )
        self.active_alerts[alert_type] = alert
        logger.warning(f"[ALERT:{severity.value}] {message}")
        return alert
    
    def _resolve_alert(self, alert_type: str):
        """Resolve an active alert."""
        if alert_type in self.active_alerts and not self.active_alerts[alert_type].resolved:
            self.active_alerts[alert_type].resolved = True
            self.active_alerts[alert_type].resolved_at = datetime.now().isoformat()
            logger.info(f"[ALERT RESOLVED] {alert_type}")


class PipelineMonitor:
    """
    Main monitoring class for the pipeline.
    
    Collects metrics, manages persistence, and triggers alerts.
    Thread-safe for concurrent access.
    """
    
    def __init__(
        self,
        run_id: str,
        metrics_file: Path = Path("data/pipeline_metrics.json"),
        history_file: Path = Path("data/pipeline_history.jsonl"),
        papers_dir: Path = Path("DataBase/Papers"),
        alert_thresholds: Optional[Dict[str, Any]] = None,
        heartbeat_interval: int = 30
    ):
        self.run_id = run_id
        self.metrics_file = Path(metrics_file)
        self.history_file = Path(history_file)
        self.papers_dir = Path(papers_dir)
        
        self.metrics = PipelineMetrics(run_id=run_id)
        self.alert_manager = AlertManager(alert_thresholds)
        
        self._lock = threading.Lock()
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_heartbeat = threading.Event()
        
        self._start_timestamp = time.time()
        
        # Ensure directories exist
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"PipelineMonitor initialized (run_id={run_id})")
    
    # =========================================================================
    # Lifecycle Methods
    # =========================================================================
    
    def start(self):
        """Start monitoring (begin heartbeat thread)."""
        with self._lock:
            self.metrics.status = PipelineStatus.RUNNING.value
            self.metrics.start_time = datetime.now().isoformat()
            self._start_timestamp = time.time()
        
        # Start heartbeat thread
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()
        
        self._collect_resource_snapshot()
        self._count_totals()
        self.save()
        
        logger.info("Pipeline monitoring started")
    
    def stop(self, graceful: bool = True, status: PipelineStatus = PipelineStatus.COMPLETED):
        """Stop monitoring and persist final metrics."""
        self._stop_heartbeat.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
        
        with self._lock:
            self.metrics.status = status.value
            self.metrics.end_time = datetime.now().isoformat()
            self.metrics.graceful_shutdown = graceful
            self.metrics.uptime_seconds = time.time() - self._start_timestamp
        
        self._collect_resource_snapshot()
        self._count_totals()
        self.save()
        self._append_to_history()
        
        logger.info(f"Pipeline monitoring stopped (status={status.value}, graceful={graceful})")
    
    # =========================================================================
    # Phase Tracking
    # =========================================================================
    
    def start_phase(self, phase: PipelinePhase):
        """Mark the start of a phase."""
        with self._lock:
            self.metrics.current_phase = phase.value
            now = datetime.now().isoformat()
            
            if phase == PipelinePhase.DISCOVERY:
                self.metrics.discovery.start_time = now
            elif phase == PipelinePhase.DOWNLOAD:
                self.metrics.download.start_time = now

            elif phase == PipelinePhase.CHUNKING:
                self.metrics.chunking.start_time = now
            elif phase == PipelinePhase.EMBEDDING:
                self.metrics.embedding.start_time = now
        
        self.heartbeat()
        logger.debug(f"Phase started: {phase.value}")
    
    def end_phase(self, phase: PipelinePhase):
        """Mark the end of a phase."""
        with self._lock:
            now = datetime.now().isoformat()
            
            if phase == PipelinePhase.DISCOVERY:
                self.metrics.discovery.end_time = now
                if self.metrics.discovery.start_time:
                    start = datetime.fromisoformat(self.metrics.discovery.start_time)
                    self.metrics.discovery.duration_seconds = (datetime.now() - start).total_seconds()
            
            elif phase == PipelinePhase.DOWNLOAD:
                self.metrics.download.end_time = now
                if self.metrics.download.start_time:
                    start = datetime.fromisoformat(self.metrics.download.start_time)
                    duration = (datetime.now() - start).total_seconds()
                    self.metrics.download.duration_seconds = duration
                    if duration > 0 and self.metrics.download.successful > 0:
                        self.metrics.download.downloads_per_minute = (
                            self.metrics.download.successful / duration * 60
                        )
            

            
            elif phase == PipelinePhase.CHUNKING:
                self.metrics.chunking.end_time = now
                if self.metrics.chunking.start_time:
                    start = datetime.fromisoformat(self.metrics.chunking.start_time)
                    duration = (datetime.now() - start).total_seconds()
                    self.metrics.chunking.duration_seconds = duration
                    if self.metrics.chunking.pdfs_processed > 0:
                        self.metrics.chunking.chunks_per_pdf_avg = (
                            self.metrics.chunking.chunks_created /
                            self.metrics.chunking.pdfs_processed
                        )
            
            elif phase == PipelinePhase.EMBEDDING:
                self.metrics.embedding.end_time = now
                if self.metrics.embedding.start_time:
                    start = datetime.fromisoformat(self.metrics.embedding.start_time)
                    duration = (datetime.now() - start).total_seconds()
                    self.metrics.embedding.duration_seconds = duration
                    if duration > 0 and self.metrics.embedding.chunks_embedded > 0:
                        self.metrics.embedding.embeddings_per_second = (
                            self.metrics.embedding.chunks_embedded / duration
                        )
                    if self.metrics.embedding.pdfs_processed > 0:
                        self.metrics.embedding.chunks_per_pdf_avg = (
                            self.metrics.embedding.chunks_created / 
                            self.metrics.embedding.pdfs_processed
                        )
        
        self.save()
        logger.debug(f"Phase ended: {phase.value}")
    
    # =========================================================================
    # Metric Updates
    # =========================================================================
    
    def update_discovery(self, **kwargs):
        """Update discovery metrics."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.metrics.discovery, key):
                    if isinstance(value, dict) and isinstance(getattr(self.metrics.discovery, key), dict):
                        getattr(self.metrics.discovery, key).update(value)
                    else:
                        setattr(self.metrics.discovery, key, value)
        self.heartbeat()
    
    def update_download(self, **kwargs):
        """Update download metrics."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.metrics.download, key):
                    if isinstance(value, dict) and isinstance(getattr(self.metrics.download, key), dict):
                        getattr(self.metrics.download, key).update(value)
                    else:
                        setattr(self.metrics.download, key, value)
        self.heartbeat()
    
    
    def update_chunking(self, **kwargs):
        """Update chunking metrics."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.metrics.chunking, key):
                    setattr(self.metrics.chunking, key, value)
        self.heartbeat()
    
    def update_embedding(self, **kwargs):
        """Update embedding metrics."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.metrics.embedding, key):
                    setattr(self.metrics.embedding, key, value)
        self.heartbeat()
    
    def increment(self, phase: str, metric: str, amount: int = 1):
        """Increment a counter metric."""
        with self._lock:
            phase_metrics = getattr(self.metrics, phase, None)
            if phase_metrics and hasattr(phase_metrics, metric):
                current = getattr(phase_metrics, metric)
                setattr(phase_metrics, metric, current + amount)
    
    # =========================================================================
    # Heartbeat & Resources
    # =========================================================================
    
    def heartbeat(self):
        """Update heartbeat timestamp."""
        with self._lock:
            self.metrics.last_heartbeat = datetime.now().isoformat()
            self.metrics.uptime_seconds = time.time() - self._start_timestamp
    
    def _heartbeat_loop(self):
        """Background thread for periodic heartbeat and resource collection."""
        while not self._stop_heartbeat.wait(timeout=self._heartbeat_interval):
            self.heartbeat()
            self._collect_resource_snapshot()
            self._check_alerts()
            self.save()
    
    def _collect_resource_snapshot(self):
        """Collect current resource usage."""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(str(self.papers_dir.parent))
            
            resources = ResourceMetrics(
                cpu_percent=cpu_percent,
                memory_mb=memory.used / (1024 * 1024),
                memory_percent=memory.percent,
                disk_used_gb=disk.used / (1024**3),
                disk_free_gb=disk.free / (1024**3),
                disk_percent=disk.percent
            )
            
            # Try to get GPU metrics
            try:
                import torch
                if torch.cuda.is_available():
                    resources.gpu_memory_mb = torch.cuda.memory_allocated() / (1024 * 1024)
                    resources.gpu_memory_percent = (
                        torch.cuda.memory_allocated() / 
                        torch.cuda.get_device_properties(0).total_memory * 100
                    )
                    # GPU utilization requires nvidia-smi or pynvml
            except ImportError:
                pass
            
            with self._lock:
                self.metrics.resources = resources
                self.metrics.resource_history.append(resources.to_dict())
                # Keep only last 100 snapshots
                if len(self.metrics.resource_history) > 100:
                    self.metrics.resource_history = self.metrics.resource_history[-100:]
                    
        except Exception as e:
            logger.debug(f"Failed to collect resource metrics: {e}")
    
    def _count_totals(self):
        """Count total papers and embeddings."""
        try:
            # Count PDFs
            if self.papers_dir.exists():
                pdf_count = len(list(self.papers_dir.glob("*.pdf")))
                with self._lock:
                    self.metrics.total_papers_in_db = pdf_count
        except Exception as e:
            logger.debug(f"Failed to count papers: {e}")
    
    def _check_alerts(self):
        """Check alert conditions and log any new alerts."""
        new_alerts = self.alert_manager.check_alerts(self.metrics)
        with self._lock:
            for alert in new_alerts:
                self.metrics.alerts.append(alert.to_dict())
    
    # =========================================================================
    # Persistence
    # =========================================================================
    
    def save(self):
        """Save current metrics to file (atomic write)."""
        try:
            temp_file = self.metrics_file.with_suffix(".tmp")
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.metrics.to_dict(), f, indent=2)
            os.replace(temp_file, self.metrics_file)
        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")
    
    def _append_to_history(self):
        """Append completed run to history file."""
        try:
            with open(self.history_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(self.metrics.to_dict()) + "\n")
            logger.info(f"Run appended to history: {self.history_file}")
        except Exception as e:
            logger.error(f"Failed to append to history: {e}")
    
    @classmethod
    def load_history(cls, history_file: Path = Path("data/pipeline_history.jsonl")) -> List[Dict[str, Any]]:
        """Load run history from file."""
        history = []
        if history_file.exists():
            with open(history_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        try:
                            history.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        return history
    
    @classmethod
    def load_current(cls, metrics_file: Path = Path("data/pipeline_metrics.json")) -> Optional[Dict[str, Any]]:
        """Load current/latest metrics from file."""
        if metrics_file.exists():
            try:
                with open(metrics_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return None
        return None
