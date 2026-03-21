"""
SME Research Assistant - Core Interfaces

Abstract base classes defining the contracts for all major components.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Iterator, Tuple
from pathlib import Path


@dataclass
class Document:
    """Represents an extracted document."""
    doi: str
    title: str
    abstract: str
    full_text: str
    sections: Dict[str, str] = field(default_factory=dict)
    section_spans: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # (start, end) positions
    metadata: Dict[str, Any] = field(default_factory=dict)
    extraction_quality: float = 1.0
    file_path: Optional[Path] = None


@dataclass
class Chunk:
    """Represents a text chunk from a document."""
    chunk_id: str
    text: str
    doi: str
    section: str = ""
    chunk_index: int = 0
    start_char: int = 0
    end_char: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None


@dataclass
class RetrievalResult:
    """Result from retrieval pipeline."""
    chunk: Chunk
    score: float
    source: str  # "semantic", "bm25", "reranked"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationResult:
    """Result from generation pipeline."""
    response: str
    citations: List[str]
    confidence: str  # "HIGH", "MEDIUM", "LOW"
    source_chunks: List[RetrievalResult]
    tokens_used: int = 0
    latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass 
class QueryContext:
    """Context for a user query."""
    query: str
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    filters: Dict[str, Any] = field(default_factory=dict)
    user_id: Optional[str] = None
    session_id: Optional[str] = None


class DocumentParser(ABC):
    """Interface for PDF document parsing."""
    
    @abstractmethod
    def parse(self, file_path: Path) -> Document:
        """Parse a PDF file and extract text content."""
        pass
    
    @abstractmethod
    def validate(self, file_path: Path) -> bool:
        """Validate if file can be parsed."""
        pass


class TextChunker(ABC):
    """Interface for text chunking strategies."""
    
    @abstractmethod
    def chunk(self, document: Document) -> List[Chunk]:
        """Split document into chunks."""
        pass


class Embedder(ABC):
    """Interface for embedding generation."""
    
    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        pass
    
    @abstractmethod
    def embed_query(self, query: str) -> List[float]:
        """Generate embedding for a query."""
        pass


class VectorStore(ABC):
    """Interface for vector storage operations."""
    
    @abstractmethod
    def upsert(self, chunks: List[Chunk]) -> None:
        """Insert or update chunks in the store."""
        pass
    
    @abstractmethod
    def search(self, query_embedding: List[float], top_k: int = 10,
               filters: Optional[Dict[str, Any]] = None) -> List[RetrievalResult]:
        """Search for similar chunks."""
        pass
    
    @abstractmethod
    def delete(self, doi: str) -> None:
        """Delete all chunks for a document."""
        pass
    
    @abstractmethod
    def count(self) -> int:
        """Get total number of chunks."""
        pass


class KeywordIndex(ABC):
    """Interface for keyword-based search (BM25)."""
    
    @abstractmethod
    def index(self, chunks: List[Chunk]) -> None:
        """Index chunks for keyword search."""
        pass
    
    @abstractmethod
    def search(self, query: str, top_k: int = 10) -> List[RetrievalResult]:
        """Search using keywords."""
        pass


class Reranker(ABC):
    """Interface for reranking search results."""
    
    @abstractmethod
    def rerank(self, query: str, results: List[RetrievalResult], 
               top_k: int = 10) -> List[RetrievalResult]:
        """Rerank results using cross-encoder."""
        pass


class LLMClient(ABC):
    """Interface for LLM interactions."""
    
    @abstractmethod
    def generate(self, prompt: str, system_prompt: str = "",
                 temperature: float = 0.1, max_tokens: int = 2000) -> str:
        """Generate a response."""
        pass
    
    @abstractmethod
    def generate_stream(self, prompt: str, system_prompt: str = "",
                        temperature: float = 0.1, max_tokens: int = 2000) -> Iterator[str]:
        """Generate a streaming response."""
        pass
    
    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.1,
             max_tokens: int = 2000) -> str:
        """Chat completion with structured messages."""
        pass


class Cache(ABC):
    """Interface for caching layer."""
    
    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        pass
    
    @abstractmethod
    def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """Set value in cache with TTL."""
        pass
    
    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete from cache."""
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """Clear all cache."""
        pass


class MetricsCollector(ABC):
    """Interface for collecting metrics."""
    
    @abstractmethod
    def log_query(self, context: QueryContext, result: GenerationResult) -> None:
        """Log a query and its result."""
        pass
    
    @abstractmethod
    def log_feedback(self, query_id: str, feedback: str, rating: int) -> None:
        """Log user feedback."""
        pass
    
    @abstractmethod
    def get_metrics(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """Get aggregated metrics for a date range."""
        pass


@dataclass
class SectionResult:
    """Result from generating one section."""
    title: str
    content: str
    citations_used: List[str] = field(default_factory=list)
    sources: List[Dict] = field(default_factory=list)
    apa_references: List[str] = field(default_factory=list)
    doi_set: set = field(default_factory=set)
    cited_dois: set = field(default_factory=set)  # P9: DOIs of facts assigned to paragraphs

