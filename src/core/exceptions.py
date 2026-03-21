"""
SME Research Assistant - Custom Exceptions

Centralized exception definitions for error handling and resilience.
"""


class SMEBaseException(Exception):
    """Base exception for all SME RAG system errors."""
    
    def __init__(self, message: str, details: dict = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


# Ingestion Exceptions
class IngestionError(SMEBaseException):
    """Errors during document ingestion."""
    pass


class PDFExtractionError(IngestionError):
    """Failed to extract text from PDF."""
    pass


class InvalidPDFError(IngestionError):
    """PDF file is invalid or corrupted."""
    pass


class DuplicateDocumentError(IngestionError):
    """Document already exists in the system."""
    pass


class LowQualityExtractionError(IngestionError):
    """Extraction quality below threshold."""
    pass


# Indexing Exceptions
class IndexingError(SMEBaseException):
    """Errors during embedding or indexing."""
    pass


class EmbeddingError(IndexingError):
    """Failed to generate embeddings."""
    pass


class VectorStoreError(IndexingError):
    """Vector store operation failed."""
    pass


class VectorStoreConnectionError(VectorStoreError):
    """Cannot connect to vector store."""
    pass


# Retrieval Exceptions  
class RetrievalError(SMEBaseException):
    """Errors during retrieval."""
    pass


class NoResultsError(RetrievalError):
    """No results found for query."""
    pass


class RerankerError(RetrievalError):
    """Reranking failed."""
    pass


# Generation Exceptions
class GenerationError(SMEBaseException):
    """Errors during LLM generation."""
    pass


class LLMConnectionError(GenerationError):
    """Cannot connect to LLM service."""
    pass


class LLMTimeoutError(GenerationError):
    """LLM request timed out."""
    pass


class LLMRateLimitError(GenerationError):
    """LLM rate limit exceeded."""
    pass


class ContextTooLongError(GenerationError):
    """Context exceeds model's maximum length."""
    pass


# Security Exceptions
class SecurityError(SMEBaseException):
    """Security-related errors."""
    pass


class AuthenticationError(SecurityError):
    """Authentication failed."""
    pass


class AuthorizationError(SecurityError):
    """User not authorized for this action."""
    pass


class InputValidationError(SecurityError):
    """Input failed validation (potential injection)."""
    pass


# Cache Exceptions
class CacheError(SMEBaseException):
    """Cache operation errors."""
    pass


class CacheConnectionError(CacheError):
    """Cannot connect to cache service."""
    pass


# Configuration Exceptions
class ConfigurationError(SMEBaseException):
    """Configuration-related errors."""
    pass


class MissingConfigError(ConfigurationError):
    """Required configuration is missing."""
    pass


# Circuit Breaker
class CircuitOpenError(SMEBaseException):
    """Circuit breaker is open, service unavailable."""
    pass
