"""
Session Cache for Sequential RAG.

Caches search results across a conversation session for faster follow-up queries.
"""

import time
import hashlib
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A cached search result."""
    results: List
    context: str
    apa_refs: List[str]
    doi_map: Dict[str, int]
    timestamp: float
    query: str


class SessionCache:
    """
    Cache for reusing search results across a conversation session.
    
    Features:
    - Query hash lookup
    - TTL-based expiration
    - LRU eviction
    """
    
    def __init__(self, max_size: int = 50, ttl_seconds: int = 3600):
        """
        Initialize session cache.
        
        Args:
            max_size: Maximum entries to store
            ttl_seconds: Time-to-live in seconds (default 1 hour)
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[str, CacheEntry] = {}
        self.access_order: List[str] = []  # LRU tracking
    
    def _hash_query(self, query: str) -> str:
        """Generate hash for query."""
        normalized = query.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def get(self, query: str) -> Optional[CacheEntry]:
        """
        Get cached results for a query.
        
        Args:
            query: Search query
            
        Returns:
            CacheEntry if found and not expired, None otherwise
        """
        key = self._hash_query(query)
        entry = self.cache.get(key)
        
        if entry is None:
            return None
        
        # Check TTL
        if time.time() - entry.timestamp > self.ttl_seconds:
            self._remove(key)
            return None
        
        # Update access order (LRU)
        self._touch(key)
        
        logger.debug(f"Cache hit for query: {query[:50]}...")
        return entry
    
    def set(
        self,
        query: str,
        results: List,
        context: str,
        apa_refs: List[str],
        doi_map: Dict[str, int]
    ):
        """
        Cache search results.
        
        Args:
            query: Search query
            results: Search results
            context: Built context string
            apa_refs: APA references
            doi_map: DOI to number mapping
        """
        # Evict if at capacity
        while len(self.cache) >= self.max_size:
            self._evict_oldest()
        
        key = self._hash_query(query)
        self.cache[key] = CacheEntry(
            results=results,
            context=context,
            apa_refs=apa_refs,
            doi_map=doi_map,
            timestamp=time.time(),
            query=query
        )
        self.access_order.append(key)
        
        logger.debug(f"Cached results for query: {query[:50]}...")
    
    def _touch(self, key: str):
        """Update access order for LRU."""
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)
    
    def _remove(self, key: str):
        """Remove entry from cache."""
        if key in self.cache:
            del self.cache[key]
        if key in self.access_order:
            self.access_order.remove(key)
    
    def _evict_oldest(self):
        """Evict least recently used entry."""
        if self.access_order:
            oldest_key = self.access_order.pop(0)
            if oldest_key in self.cache:
                del self.cache[oldest_key]
                logger.debug(f"Evicted oldest cache entry")
    
    def clear(self):
        """Clear all cached entries."""
        self.cache.clear()
        self.access_order.clear()
        logger.info("Session cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "entries": len(self.cache),
            "max_size": self.max_size,
            "utilization": len(self.cache) / self.max_size if self.max_size > 0 else 0
        }
    
    def find_similar(self, query: str, threshold: float = 0.8) -> Optional[CacheEntry]:
        """
        Find cached results for semantically similar query.
        
        This is a simple implementation using word overlap.
        For production, use embedding similarity.
        
        Args:
            query: Search query
            threshold: Similarity threshold (0.0-1.0)
            
        Returns:
            CacheEntry if similar query found, None otherwise
        """
        query_words = set(query.lower().split())
        
        best_match = None
        best_score = 0.0
        
        for entry in self.cache.values():
            # Check TTL
            if time.time() - entry.timestamp > self.ttl_seconds:
                continue
            
            # Calculate word overlap
            cached_words = set(entry.query.lower().split())
            
            if not query_words or not cached_words:
                continue
            
            intersection = len(query_words & cached_words)
            union = len(query_words | cached_words)
            score = intersection / union if union > 0 else 0
            
            if score > best_score and score >= threshold:
                best_score = score
                best_match = entry
        
        if best_match:
            logger.debug(f"Found similar cached query (score={best_score:.2f})")
        
        return best_match


def create_session_cache(max_size: int = 50) -> SessionCache:
    """Factory function to create session cache."""
    return SessionCache(max_size=max_size)
