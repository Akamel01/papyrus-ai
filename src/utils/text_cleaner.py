"""
Text Cleaner for PDF Extraction Artifacts.

Cleans common PDF-to-text conversion errors:
- Ligature characters (fi, fl, ff)
- Math symbol corruption (¼ → 1/4, × → x)
- Special character sequences (jjDVjj → |DV|)
- UTF-8 encoding issues
"""

import re
from typing import Dict, List


# Mapping of corrupted characters to their intended representations
CHAR_FIXES: Dict[str, str] = {
    # Fractions
    '¼': '1/4',
    '½': '1/2',
    '¾': '3/4',
    '⅓': '1/3',
    '⅔': '2/3',
    
    # Math operators
    '×': ' × ',
    '÷': ' / ',
    '±': ' ± ',
    '≤': ' ≤ ',
    '≥': ' ≥ ',
    '≠': ' ≠ ',
    '≈': ' ≈ ',
    '∞': 'infinity',
    
    # Greek letters (if corrupted)
    'α': 'alpha',
    'β': 'beta',
    'γ': 'gamma',
    'δ': 'delta',
    'σ': 'sigma',
    'μ': 'mu',
    
    # Common ligature corruptions
    'ﬁ': 'fi',
    'ﬂ': 'fl',
    'ﬀ': 'ff',
    'ﬃ': 'ffi',
    'ﬄ': 'ffl',
    
    # Quotation marks
    '"': '"',
    '"': '"',
    ''': "'",
    ''': "'",
    '–': '-',
    '—': '-',
    
    # Arrows
    '→': '->',
    '←': '<-',
    '↔': '<->',
}

# Regex patterns for common PDF artifacts
REGEX_FIXES: List[tuple] = [
    # Double pipe notation: jjXjj → |X|
    (r'jj([A-Za-z]+)jj', r'|\1|'),
    
    # Subscript/superscript markers: _i, ^2
    (r'(\w)_(\d)', r'\1_\2'),
    
    # Multiple spaces
    (r'\s{2,}', ' '),
    
    # Broken equations: "TTC ¼ D" → "TTC = D"
    (r'(\w+)\s*¼\s*', r'\1 = '),
    
    # Line breaks in middle of words
    (r'(\w+)-\n(\w+)', r'\1\2'),
    
    # Paragraph markers/page numbers in text
    (r'\n\d+\n', '\n'),
    
    # Reference markers that got mangled
    (r'\[(\d+)\]', r'[\1]'),
    
    # Excessive newlines
    (r'\n{3,}', '\n\n'),
]


def clean_text(text: str, preserve_math: bool = False) -> str:
    """
    Clean text extracted from PDF.
    
    Args:
        text: Raw text from PDF extraction
        preserve_math: If True, keep math symbols as-is
        
    Returns:
        Cleaned text
    """
    if not text:
        return ""
    
    # Apply character fixes
    for bad_char, good_char in CHAR_FIXES.items():
        if preserve_math and bad_char in ['×', '÷', '±', '≤', '≥']:
            continue
        text = text.replace(bad_char, good_char)
    
    # Apply regex fixes
    for pattern, replacement in REGEX_FIXES:
        text = re.sub(pattern, replacement, text)
    
    # Normalize whitespace
    text = ' '.join(text.split())
    
    return text.strip()


def clean_chunk_text(chunk_text: str) -> str:
    """
    Clean a single chunk's text for better readability.
    """
    return clean_text(chunk_text, preserve_math=True)


def batch_clean(texts: List[str]) -> List[str]:
    """Clean a batch of texts."""
    return [clean_text(t) for t in texts]


# For use in retrieval pipeline
class TextCleaner:
    """Stateless text cleaner for pipeline integration."""
    
    @staticmethod
    def clean(text: str) -> str:
        return clean_text(text)
    
    @staticmethod
    def clean_for_display(text: str) -> str:
        """Clean text specifically for UI display."""
        cleaned = clean_text(text, preserve_math=True)
        # Additional display-specific fixes
        cleaned = re.sub(r'\b(\w+)_(\w+)\b', r'\1<sub>\2</sub>', cleaned)  # Subscripts
        return cleaned
