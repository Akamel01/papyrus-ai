"""
SME Research Assistant - Security: Input Sanitizer

Protects against prompt injection and validates user inputs.
"""

import re
from typing import Tuple, List
from src.core.exceptions import InputValidationError


class InputSanitizer:
    """Sanitize and validate user inputs."""
    
    # Patterns that indicate prompt injection attempts
    INJECTION_PATTERNS = [
        r"ignore\s+(previous|above|all)\s+(instructions?|prompts?|rules?)",
        r"forget\s+(everything|all|previous)",
        r"new\s+instructions?:",
        r"system\s*:\s*",
        r"assistant\s*:\s*",
        r"<\|.*?\|>",  # Special tokens
        r"\[INST\]",
        r"\[/INST\]",
        r"<<SYS>>",
        r"<</SYS>>",
        r"you\s+are\s+now\s+",
        r"pretend\s+(you\s+are|to\s+be)",
        r"act\s+as\s+if",
        r"roleplay\s+as",
        r"jailbreak",
        r"dan\s+mode",
    ]
    
    # Characters that could be used for injection
    SUSPICIOUS_CHARS = ['\\x00', '\\x1b', '\x00', '\x1b']
    
    # Max lengths
    MAX_QUERY_LENGTH = 2000
    MAX_MESSAGE_LENGTH = 10000
    
    def __init__(self, max_query_length: int = 2000):
        self.max_query_length = max_query_length
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.INJECTION_PATTERNS
        ]
    
    def sanitize_query(self, query: str) -> Tuple[str, List[str]]:
        """
        Sanitize a user query.
        
        Args:
            query: Raw user input
            
        Returns:
            Tuple of (sanitized_query, list_of_warnings)
            
        Raises:
            InputValidationError: If query fails validation
        """
        warnings = []
        
        if not query or not query.strip():
            raise InputValidationError("Query cannot be empty")
        
        # Check length
        if len(query) > self.max_query_length:
            raise InputValidationError(
                f"Query exceeds maximum length of {self.max_query_length} characters",
                {"length": len(query), "max": self.max_query_length}
            )
        
        # Remove null bytes and control characters
        sanitized = self._remove_control_chars(query)
        
        # Check for injection patterns
        injection_found = self._check_injection_patterns(sanitized)
        if injection_found:
            warnings.append(f"Potentially suspicious pattern detected: {injection_found}")
            # Don't block, just warn and log - could be false positive
        
        # Normalize whitespace
        sanitized = ' '.join(sanitized.split())
        
        return sanitized, warnings
    
    def _remove_control_chars(self, text: str) -> str:
        """Remove control characters except newlines and tabs."""
        # Keep printable chars, newlines, and tabs
        return ''.join(
            char for char in text 
            if char.isprintable() or char in '\n\t'
        )
    
    def _check_injection_patterns(self, text: str) -> str:
        """Check for prompt injection patterns. Returns found pattern or empty string."""
        for pattern in self._compiled_patterns:
            match = pattern.search(text)
            if match:
                return match.group()
        return ""
    
    def sanitize_for_prompt(self, text: str) -> str:
        """
        Sanitize text that will be inserted into a prompt.
        This adds delimiters to clearly separate user content.
        """
        # Escape any potential delimiter characters
        sanitized = text.replace("```", "'''")
        sanitized = sanitized.replace("---", "___")
        
        return sanitized
    
    def validate_doi(self, doi: str) -> bool:
        """Validate DOI format."""
        # DOI format: 10.PREFIX/SUFFIX
        pattern = r'^10\.\d{4,}/[^\s]+$'
        return bool(re.match(pattern, doi))
    
    def sanitize_feedback(self, feedback: str) -> str:
        """Sanitize user feedback text."""
        if len(feedback) > 1000:
            feedback = feedback[:1000]
        return self._remove_control_chars(feedback).strip()


# Singleton instance
_sanitizer = None


def get_sanitizer(max_query_length: int = 2000) -> InputSanitizer:
    """Get or create sanitizer instance."""
    global _sanitizer
    if _sanitizer is None:
        _sanitizer = InputSanitizer(max_query_length)
    return _sanitizer
