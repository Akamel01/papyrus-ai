"""
SME Research Assistant - PDF Parser

Extracts text content from PDF files using pymupdf4llm with fallback.
"""

import fitz  # PyMuPDF
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import re
import logging

from src.core.interfaces import DocumentParser, Document
from src.core.exceptions import PDFExtractionError, InvalidPDFError, LowQualityExtractionError
from src.utils.helpers import extract_doi_from_filename, clean_text

logger = logging.getLogger(__name__)


class PyMuPDFParser(DocumentParser):
    """
    PDF parser using PyMuPDF with optional pymupdf4llm for markdown extraction.
    """
    
    def __init__(self, quality_threshold: float = 0.7, use_markdown: bool = False):
        """
        Initialize parser.
        
        Args:
            quality_threshold: Minimum extraction quality score (0-1)
            use_markdown: Whether to try pymupdf4llm first
        """
        self.quality_threshold = quality_threshold
        self.use_markdown = use_markdown
        self._has_pymupdf4llm = self._check_pymupdf4llm()
        
        # Suppress noisy MuPDF/LCMS warnings (e.g. cmsOpenProfileFromMem)
        fitz.TOOLS.mupdf_display_errors = False
        fitz.TOOLS.mupdf_warnings = False
    
    def _check_pymupdf4llm(self) -> bool:
        """Check if pymupdf4llm is available."""
        try:
            import pymupdf4llm
            return True
        except ImportError:
            logger.warning("pymupdf4llm not installed, using fallback extraction")
            return False
    
    def validate(self, file_path: Path) -> bool:
        """Validate if file is a valid PDF."""
        try:
            if not file_path.exists():
                return False
            if not file_path.suffix.lower() == '.pdf':
                return False
            # Try to open the PDF
            doc = fitz.open(file_path)
            is_valid = doc.page_count > 0
            doc.close()
            return is_valid
        except Exception:
            return False
    
    def parse(self, file_path: Path) -> Document:
        """
        Parse a PDF file and extract content.
        
        Args:
            file_path: Path to PDF file
            
        Returns:
            Document object with extracted content
            
        Raises:
            InvalidPDFError: If file is not a valid PDF
            PDFExtractionError: If extraction fails
            LowQualityExtractionError: If extraction quality is below threshold
        """
        file_path = Path(file_path)
        
        if not self.validate(file_path):
            raise InvalidPDFError(f"Invalid PDF file: {file_path}")
        
        doi = extract_doi_from_filename(file_path.name)
        
        try:
            # Try markdown extraction if explicitly enabled
            if self.use_markdown and self._has_pymupdf4llm:
                try:
                    return self._parse_markdown(file_path, doi)
                except Exception as e:
                    logger.warning(f"Markdown extraction failed for {file_path.name}, falling back: {e}")
            
            # Standard extraction (default)
            return self._parse_standard(file_path, doi)
            
        except Exception as e:
            raise PDFExtractionError(
                f"Failed to extract text from {file_path.name}: {str(e)}",
                {"file": str(file_path), "error": str(e)}
            )
    
    def _parse_markdown(self, file_path: Path, doi: str) -> Document:
        """Extract using pymupdf4llm for structured markdown."""
        import pymupdf4llm
        
        md_text = pymupdf4llm.to_markdown(str(file_path))
        
        # Parse markdown to extract sections
        sections, section_spans = self._parse_sections_from_markdown(md_text)
        title = self._extract_title(md_text, sections)
        abstract = sections.get('abstract', '')
        
        quality = self._estimate_quality(md_text)
        
        if quality < self.quality_threshold:
            raise LowQualityExtractionError(
                f"Extraction quality {quality:.2f} below threshold {self.quality_threshold}",
                {"doi": doi, "quality": quality}
            )
        
        return Document(
            doi=doi,
            title=title,
            abstract=abstract,
            full_text=md_text,
            sections=sections,
            section_spans=section_spans,
            metadata={
                "extraction_method": "pymupdf4llm",
                "file_path": str(file_path),
                "page_count": self._get_page_count(file_path)
            },
            extraction_quality=quality,
            file_path=file_path
        )
    
    def _parse_standard(self, file_path: Path, doi: str) -> Document:
        """Extract using standard PyMuPDF."""
        doc = fitz.open(file_path)
        
        full_text = ""
        for page in doc:
            full_text += page.get_text() + "\n\n"
        
        doc.close()
        
        # Clean the extracted text
        full_text = clean_text(full_text)
        
        # Try to identify sections
        sections, section_spans = self._parse_sections_from_text(full_text)
        title = self._extract_title(full_text, sections)
        abstract = sections.get('abstract', '')
        
        quality = self._estimate_quality(full_text)
        
        if quality < self.quality_threshold:
            raise LowQualityExtractionError(
                f"Extraction quality {quality:.2f} below threshold {self.quality_threshold}",
                {"doi": doi, "quality": quality}
            )
        
        return Document(
            doi=doi,
            title=title,
            abstract=abstract,
            full_text=full_text,
            sections=sections,
            section_spans=section_spans,
            metadata={
                "extraction_method": "pymupdf",
                "file_path": str(file_path),
                "page_count": self._get_page_count(file_path)
            },
            extraction_quality=quality,
            file_path=file_path
        )
    
    def _get_page_count(self, file_path: Path) -> int:
        """Get number of pages in PDF."""
        doc = fitz.open(file_path)
        count = doc.page_count
        doc.close()
        return count
    
    def _parse_sections_from_markdown(self, text: str) -> Tuple[Dict[str, str], Dict[str, Tuple[int, int]]]:
        """Parse sections from markdown text. Returns (sections, section_spans)."""
        sections = {}
        section_spans = {}
        
        # Look for markdown headers
        pattern = r'^#+\s*(.+?)$'
        matches = list(re.finditer(pattern, text, re.MULTILINE))
        
        for i, match in enumerate(matches):
            header = match.group(1).strip().lower()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            
            # Normalize section names
            normalized = self._normalize_section_name(header)
            if normalized:
                sections[normalized] = content
                section_spans[normalized] = (start, end)
        
        return sections, section_spans
    
    def _parse_sections_from_text(self, text: str) -> Tuple[Dict[str, str], Dict[str, Tuple[int, int]]]:
        """Parse sections from plain text. Returns (sections, section_spans)."""
        sections = {}
        section_spans = {}
        
        # Common section patterns in academic papers
        section_patterns = [
            (r'abstract[:\s]*(.+?)(?=introduction|background|$)', 'abstract'),
            (r'introduction[:\s]*(.+?)(?=methods|methodology|materials|background|$)', 'introduction'),
            (r'(?:methods|methodology|materials and methods)[:\s]*(.+?)(?=results|findings|$)', 'methods'),
            (r'results[:\s]*(.+?)(?=discussion|conclusion|$)', 'results'),
            (r'discussion[:\s]*(.+?)(?=conclusion|references|$)', 'discussion'),
            (r'conclusions?[:\s]*(.+?)(?=references|acknowledgment|$)', 'conclusion'),
        ]
        
        for pattern, name in section_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                section_start = match.start(1)
                section_end = min(match.end(1), section_start + 5000)  # Limit size
                sections[name] = match.group(1).strip()[:5000]
                section_spans[name] = (section_start, section_end)
        
        return sections, section_spans
    
    def _normalize_section_name(self, name: str) -> Optional[str]:
        """Normalize section name to standard format."""
        name = name.lower().strip()
        
        mappings = {
            'abstract': 'abstract',
            'summary': 'abstract',
            'introduction': 'introduction',
            'background': 'introduction',
            'methods': 'methods',
            'methodology': 'methods',
            'materials and methods': 'methods',
            'results': 'results',
            'findings': 'results',
            'discussion': 'discussion',
            'conclusion': 'conclusion',
            'conclusions': 'conclusion',
            'references': 'references',
        }
        
        for key, value in mappings.items():
            if key in name:
                return value
        
        return None
    
    def _extract_title(self, text: str, sections: Dict[str, str]) -> str:
        """Extract document title."""
        # Title is usually the first non-empty line
        lines = text.strip().split('\n')
        for line in lines[:10]:  # Check first 10 lines
            line = line.strip()
            # Skip headers, short lines, and common non-title patterns
            if line and len(line) > 10 and len(line) < 300:
                if not line.startswith('#'):
                    line = line.lstrip('#').strip()
                if not re.match(r'^(abstract|introduction|doi|volume|page)', line.lower()):
                    return line
        
        return "Unknown Title"
    
    def _estimate_quality(self, text: str) -> float:
        """
        Estimate extraction quality based on heuristics.
        
        Returns score between 0 and 1.
        """
        if not text or len(text) < 100:
            return 0.0
        
        score = 1.0
        
        # Penalize very short extractions
        if len(text) < 1000:
            score -= 0.3
        
        # Penalize excessive special characters (OCR errors)
        special_ratio = len(re.findall(r'[^\w\s.,;:!?()-]', text)) / len(text)
        if special_ratio > 0.1:
            score -= 0.2
        
        # Penalize missing common words (indicates poor extraction)
        common_words = ['the', 'and', 'of', 'to', 'in', 'a']
        text_lower = text.lower()
        found_common = sum(1 for w in common_words if w in text_lower)
        if found_common < 3:
            score -= 0.2
        
        # Penalize excessive whitespace
        whitespace_ratio = len(re.findall(r'\s{3,}', text)) / max(len(text) // 100, 1)
        if whitespace_ratio > 5:
            score -= 0.1
        
        # Bonus for structured content (sections)
        if re.search(r'(abstract|introduction|methods|results|conclusion)', text.lower()):
            score += 0.1
        
        return max(0.0, min(1.0, score))


def create_parser(quality_threshold: float = 0.7) -> PyMuPDFParser:
    """Factory function to create a PDF parser."""
    return PyMuPDFParser(quality_threshold=quality_threshold)
