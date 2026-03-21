"""
SME Research Assistant - Text Preprocessor

Cleans and normalizes extracted text from PDFs.
"""

import re
from typing import Dict, Any


class TextPreprocessor:
    """
    Preprocessor for cleaning extracted PDF text.
    """
    
    def __init__(self):
        # Patterns to remove
        self.remove_patterns = [
            r'^\s*\d+\s*$',  # Lone page numbers
            r'^\s*-\s*\d+\s*-\s*$',  # Page numbers with dashes
            r'^\s*Page\s+\d+\s*(of\s+\d+)?\s*$',  # "Page X of Y"
            r'©.*?reserved\.?',  # Copyright notices
            r'Downloaded from.*?$',  # Download notices
            r'^\s*https?://\S+\s*$',  # Standalone URLs
        ]
        
        self._compiled_remove = [
            re.compile(p, re.IGNORECASE | re.MULTILINE) 
            for p in self.remove_patterns
        ]
    
    def preprocess(self, text: str) -> str:
        """
        Clean and normalize text.
        
        Args:
            text: Raw extracted text
            
        Returns:
            Cleaned text
        """
        if not text:
            return ""
        
        # Remove unwanted patterns
        for pattern in self._compiled_remove:
            text = pattern.sub('', text)
        
        # Normalize whitespace
        text = self._normalize_whitespace(text)
        
        # Fix common OCR errors
        text = self._fix_ocr_errors(text)
        
        # Normalize special characters
        text = self._normalize_special_chars(text)
        
        # Remove excessive punctuation
        text = self._clean_punctuation(text)
        
        return text.strip()
    
    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace while preserving paragraph breaks."""
        # Replace tabs with spaces
        text = text.replace('\t', ' ')
        
        # Normalize line endings
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # Replace multiple spaces with single space
        text = re.sub(r' +', ' ', text)
        
        # Replace 3+ newlines with 2
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Remove trailing whitespace on lines
        text = re.sub(r' +\n', '\n', text)
        
        return text
    
    def _fix_ocr_errors(self, text: str) -> str:
        """Fix common OCR errors."""
        replacements = {
            'ﬁ': 'fi',
            'ﬂ': 'fl',
            'ﬀ': 'ff',
            'ﬃ': 'ffi',
            'ﬄ': 'ffl',
            '–': '-',  # en-dash
            '—': '-',  # em-dash
            '"': '"',
            '"': '"',
            ''': "'",
            ''': "'",
            '…': '...',
            '\u00a0': ' ',  # non-breaking space
            '\u2002': ' ',  # en space
            '\u2003': ' ',  # em space
        }
        
        for old, new in replacements.items():
            text = text.replace(old, new)
        
        return text
    
    def _normalize_special_chars(self, text: str) -> str:
        """Normalize special characters and symbols."""
        # Greek letters commonly used in academic papers
        greek_map = {
            'α': 'alpha', 'β': 'beta', 'γ': 'gamma', 'δ': 'delta',
            'ε': 'epsilon', 'μ': 'mu', 'σ': 'sigma', 'π': 'pi',
            'λ': 'lambda', 'θ': 'theta', 'ω': 'omega', 'ρ': 'rho',
        }
        # Don't replace, just leave them as is for now
        # They might be important for scientific context
        
        # Remove zero-width characters
        text = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', text)
        
        return text
    
    def _clean_punctuation(self, text: str) -> str:
        """Clean up punctuation issues."""
        # Fix missing space after period
        text = re.sub(r'\.([A-Z])', r'. \1', text)
        
        # Remove excessive punctuation
        text = re.sub(r'[.]{4,}', '...', text)
        text = re.sub(r'[-]{3,}', '--', text)
        
        return text
    
    def extract_metadata(self, text: str) -> Dict[str, Any]:
        """
        Extract metadata from text.
        
        Returns dict with detected metadata.
        """
        metadata = {}
        
        # Try to find year
        year_match = re.search(r'\b(19|20)\d{2}\b', text[:2000])
        if year_match:
            metadata['year'] = int(year_match.group())
        
        # Try to find email (indicates author)
        email_match = re.search(r'[\w.-]+@[\w.-]+\.\w+', text[:3000])
        if email_match:
            metadata['has_email'] = True
        
        # Count approximate words
        words = len(text.split())
        metadata['word_count'] = words
        
        # Estimate reading time (average 200 wpm)
        metadata['reading_time_minutes'] = words // 200
        
        return metadata


def create_preprocessor() -> TextPreprocessor:
    """Factory function to create a preprocessor."""
    return TextPreprocessor()
