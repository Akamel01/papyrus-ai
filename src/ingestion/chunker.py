"""
SME Research Assistant - Text Chunker

Hierarchical chunking strategy for academic papers.
Phase 4: Equation-aware splitting to prevent mid-equation chunk breaks.
"""

import tiktoken
from typing import List, Optional, Dict, Tuple
import re
import logging

from src.core.interfaces import TextChunker, Document, Chunk
from src.utils.helpers import generate_chunk_id

logger = logging.getLogger(__name__)

# --- Equation Detection Patterns (Phase 4) ---
# LaTeX display math: $$...$$, \[...\], \begin{equation}...\end{equation},
#                     \begin{align}...\end{align}, \begin{gather}...\end{gather}
_LATEX_DISPLAY = re.compile(
    r'\$\$.+?\$\$'
    r'|\\\[.+?\\\]'
    r'|\\begin\{(?:equation|align|gather|eqnarray|multline)\*?\}.+?\\end\{(?:equation|align|gather|eqnarray|multline)\*?\}',
    re.DOTALL
)
# Inline math: $...$  (single-line only, min 2 chars to avoid false positives like $5)
_INLINE_MATH = re.compile(r'(?<!\$)\$(?!\$)([^$\n]{2,}?)\$(?!\$)')
# Unicode math operator blocks: only true operators (∀∃∑∫≤≥±×÷ etc.)
# EXCLUDES U+1D400-1D7FF (Mathematical Alphanumeric Symbols) which PDFs use for styled text
_MATH_UNICODE = re.compile(r'[\u2200-\u22FF\u2A00-\u2AFF]{5,}')


class HierarchicalChunker(TextChunker):
    """
    Hierarchical text chunker optimized for academic papers.
    
    Creates three levels of chunks:
    1. Document summary (abstract + title)
    2. Section-level chunks
    3. Paragraph-level chunks with overlap
    """
    
    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
        min_chunk_size: int = 100,
        tokenizer_name: str = "cl100k_base"
    ):
        """
        Initialize chunker.
        
        Args:
            chunk_size: Target chunk size in tokens
            chunk_overlap: Overlap between chunks in tokens
            min_chunk_size: Minimum chunk size (smaller chunks are merged)
            tokenizer_name: Tiktoken tokenizer to use
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        
        try:
            self.tokenizer = tiktoken.get_encoding(tokenizer_name)
        except Exception:
            logger.warning(f"Tokenizer {tokenizer_name} not found, using cl100k_base")
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.tokenizer.encode(text))
    
    # --- Phase 4: Equation Boundary Detection ---
    
    @staticmethod
    def _find_equation_spans(text: str) -> List[Tuple[int, int]]:
        """
        Find all equation boundaries in text.
        
        Returns sorted, merged list of (start, end) character positions
        covering all detected equations (LaTeX display, inline, Unicode blocks).
        """
        spans = []
        
        for pattern in (_LATEX_DISPLAY, _INLINE_MATH, _MATH_UNICODE):
            for m in pattern.finditer(text):
                spans.append((m.start(), m.end()))
        
        if not spans:
            return []
        
        # Sort and merge overlapping spans
        spans.sort()
        merged = [spans[0]]
        for start, end in spans[1:]:
            if start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        
        return merged
    
    @staticmethod
    def _count_equations_in(text: str) -> int:
        """Count equations in a text fragment."""
        count = 0
        for pattern in (_LATEX_DISPLAY, _INLINE_MATH, _MATH_UNICODE):
            count += len(pattern.findall(text))
        return count
    
    @staticmethod
    def _is_inside_equation(pos: int, eq_spans: List[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        """
        Check if character position falls inside an equation span.
        Returns the equation span (start, end) if inside, None otherwise.
        """
        for start, end in eq_spans:
            if start <= pos < end:
                return (start, end)
            if start > pos:
                break  # Spans are sorted
        return None
    
    def chunk(self, document: Document) -> List[Chunk]:
        """
        Split document into hierarchical chunks.
        
        Args:
            document: Document to chunk
            
        Returns:
            List of Chunk objects
        """
        chunks = []
        chunk_index = 0
        
        # Level 1: Document summary chunk
        summary_chunk = self._create_summary_chunk(document, chunk_index)
        if summary_chunk:
            chunks.append(summary_chunk)
            chunk_index += 1
        
        # Level 2 & 3: Section and paragraph chunks
        if document.sections:
            for section_name, section_text in document.sections.items():
                if section_name == 'references':  # Skip references
                    continue
                    
                section_chunks = self._chunk_section(
                    document.doi, 
                    section_name, 
                    section_text,
                    chunk_index
                )
                chunks.extend(section_chunks)
                chunk_index += len(section_chunks)
            
            # Gap-filling: chunk text not covered by any section
            gaps = self._identify_gaps(len(document.full_text), document.section_spans)
            for gap_start, gap_end in gaps:
                gap_text = document.full_text[gap_start:gap_end].strip()
                if len(gap_text) < 50:  # Skip trivial gaps (whitespace, headers)
                    continue
                
                gap_chunks = self._chunk_text(
                    document.doi,
                    "uncategorized",
                    gap_text,
                    chunk_index
                )
                chunks.extend(gap_chunks)
                chunk_index += len(gap_chunks)
                logger.info(f"[GAP-FILL] DOI={document.doi}, Gap chars={len(gap_text)}, Chunks={len(gap_chunks)}")
        else:
            # No sections detected, chunk the full text
            full_text_chunks = self._chunk_text(
                document.doi,
                "full_text",
                document.full_text,
                chunk_index
            )
            chunks.extend(full_text_chunks)
        
        logger.debug(f"Created {len(chunks)} chunks for DOI {document.doi}")
        return chunks
    
    def _create_summary_chunk(self, document: Document, chunk_index: int) -> Optional[Chunk]:
        """Create a document summary chunk from title and abstract."""
        parts = []
        
        if document.title and document.title != "Unknown Title":
            parts.append(f"Title: {document.title}")
        
        if document.abstract:
            parts.append(f"Abstract: {document.abstract}")
        
        if not parts:
            return None
        
        text = "\n\n".join(parts)
        
        # Truncate if too long
        if self.count_tokens(text) > self.chunk_size * 2:
            text = self._truncate_to_tokens(text, self.chunk_size * 2)
        
        return Chunk(
            chunk_id=generate_chunk_id(document.doi, "summary", chunk_index),
            text=text,
            doi=document.doi,
            section="summary",
            chunk_index=chunk_index,
            metadata={
                "level": "document",
                "title": document.title,
                "has_abstract": bool(document.abstract)
            }
        )
    
    def _chunk_section(
        self, 
        doi: str, 
        section_name: str, 
        text: str,
        start_index: int
    ) -> List[Chunk]:
        """Chunk a section of the document."""
        return self._chunk_text(doi, section_name, text, start_index)
    
    def _chunk_text(
        self,
        doi: str,
        section: str,
        text: str,
        start_index: int
    ) -> List[Chunk]:
        """
        Chunk text with overlap using recursive splitting.
        """
        if not text or not text.strip():
            return []
        
        chunks = []
        current_index = start_index
        
        # Split by paragraphs first
        paragraphs = self._split_into_paragraphs(text)
        
        current_chunk_text = ""
        current_chunk_start = 0
        
        for para in paragraphs:
            para_tokens = self.count_tokens(para)
            current_tokens = self.count_tokens(current_chunk_text)
            
            # If single paragraph exceeds chunk size, split it further
            if para_tokens > self.chunk_size:
                # Save current chunk if it has content
                if current_chunk_text.strip():
                    chunks.append(self._create_chunk(
                        doi, section, current_chunk_text, current_index,
                        current_chunk_start
                    ))
                    current_index += 1
                    current_chunk_text = ""
                
                # Split the large paragraph
                sub_chunks = self._split_large_paragraph(
                    doi, section, para, current_index
                )
                chunks.extend(sub_chunks)
                current_index += len(sub_chunks)
                current_chunk_start = 0
                continue
            
            # Check if adding this paragraph exceeds chunk size
            if current_tokens + para_tokens > self.chunk_size:
                # Save current chunk
                if current_chunk_text.strip():
                    chunks.append(self._create_chunk(
                        doi, section, current_chunk_text, current_index,
                        current_chunk_start
                    ))
                    current_index += 1
                
                # Start new chunk with overlap
                overlap_text = self._get_overlap_text(current_chunk_text)
                current_chunk_text = overlap_text + para
                current_chunk_start = 0
            else:
                current_chunk_text += "\n\n" + para if current_chunk_text else para
        
        # Don't forget the last chunk
        if current_chunk_text.strip():
            if self.count_tokens(current_chunk_text) >= self.min_chunk_size:
                chunks.append(self._create_chunk(
                    doi, section, current_chunk_text, current_index,
                    current_chunk_start
                ))
            elif chunks:
                # Merge with previous chunk if too small
                chunks[-1].text += "\n\n" + current_chunk_text
        
        return chunks
    
    def _split_into_paragraphs(self, text: str) -> List[str]:
        """
        Split text into paragraphs, ensuring no split happens mid-equation.
        Phase 4: equation-aware paragraph splitting.
        """
        # Find equation spans in the full text
        eq_spans = self._find_equation_spans(text)
        
        # Find potential split positions (double newlines)
        raw_paragraphs = re.split(r'\n\s*\n', text)
        
        if not eq_spans:
            # No equations — use standard splitting
            return [p.strip() for p in raw_paragraphs if p.strip()]
        
        # Rebuild paragraphs, merging any that split mid-equation
        merged_paragraphs = []
        accumulator = ""
        char_pos = 0  # Track position in original text
        
        for para in raw_paragraphs:
            # Find where this paragraph starts in the original text
            para_start = text.find(para.strip(), char_pos) if para.strip() else char_pos
            if para_start == -1:
                para_start = char_pos
            para_end = para_start + len(para.strip())
            
            accumulator += ("\n\n" + para if accumulator else para)
            char_pos = para_end
            
            # Check if the split point (para_end) is inside an equation
            eq_span = self._is_inside_equation(para_end, eq_spans)
            if eq_span:
                # Don't split here — keep accumulating
                continue
            
            # Safe to split — emit accumulated text
            if accumulator.strip():
                merged_paragraphs.append(accumulator.strip())
            accumulator = ""
        
        # Don't forget trailing content
        if accumulator.strip():
            merged_paragraphs.append(accumulator.strip())
        
        return merged_paragraphs
    
    def _split_large_paragraph(
        self,
        doi: str,
        section: str,
        text: str,
        start_index: int
    ) -> List[Chunk]:
        """
        Split a large paragraph that exceeds chunk size.
        Phase 4: equation-aware — never splits mid-equation.
        """
        chunks = []
        current_index = start_index
        eq_spans = self._find_equation_spans(text)
        
        # Split by sentences
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        current_chunk = ""
        in_equation_accumulation = False
        
        for sentence in sentences:
            would_exceed = self.count_tokens(current_chunk + " " + sentence) > self.chunk_size
            
            if would_exceed and not in_equation_accumulation:
                if current_chunk:
                    chunks.append(self._create_chunk(
                        doi, section, current_chunk, current_index, 0
                    ))
                    current_index += 1
                    
                    # Add overlap
                    overlap = self._get_overlap_text(current_chunk)
                    current_chunk = overlap + sentence
                else:
                    # Single sentence exceeds limit, truncate
                    truncated = self._truncate_to_tokens(sentence, self.chunk_size)
                    chunks.append(self._create_chunk(
                        doi, section, truncated, current_index, 0
                    ))
                    current_index += 1
                    current_chunk = ""
            else:
                current_chunk += " " + sentence if current_chunk else sentence
            
            # Phase 4: Check if current chunk ends inside an equation
            # If so, keep accumulating even if over chunk_size (up to 2x limit)
            chunk_end_in_text = text.find(sentence, 0) + len(sentence) if sentence else 0
            eq_span = self._is_inside_equation(chunk_end_in_text, eq_spans)
            in_equation_accumulation = eq_span is not None
            
            # Safety valve: if accumulated > 2x chunk_size, force split
            if in_equation_accumulation and self.count_tokens(current_chunk) > self.chunk_size * 2:
                logger.warning(f"[CHUNK-EQ] Equation too large to preserve, forced split at {self.count_tokens(current_chunk)} tokens")
                in_equation_accumulation = False
        
        if current_chunk:
            chunks.append(self._create_chunk(
                doi, section, current_chunk, current_index, 0
            ))
        
        return chunks
    
    def _get_overlap_text(self, text: str) -> str:
        """Get the last portion of text for overlap."""
        if not text:
            return ""
        
        # Get roughly overlap_size tokens from the end
        tokens = self.tokenizer.encode(text)
        if len(tokens) <= self.chunk_overlap:
            return text
        
        overlap_tokens = tokens[-self.chunk_overlap:]
        return self.tokenizer.decode(overlap_tokens)
    
    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """Truncate text to a maximum number of tokens."""
        tokens = self.tokenizer.encode(text)
        if len(tokens) <= max_tokens:
            return text
        return self.tokenizer.decode(tokens[:max_tokens])
    
    def _create_chunk(
        self,
        doi: str,
        section: str,
        text: str,
        index: int,
        start_char: int
    ) -> Chunk:
        """Create a Chunk object with equation metadata (Phase 4)."""
        stripped = text.strip()
        eq_count = self._count_equations_in(stripped)
        
        return Chunk(
            chunk_id=generate_chunk_id(doi, section, index),
            text=stripped,
            doi=doi,
            section=section,
            chunk_index=index,
            start_char=start_char,
            end_char=start_char + len(text),
            metadata={
                "level": "paragraph",
                "token_count": self.count_tokens(stripped),
                "equation_count": eq_count
            }
        )

    def _identify_gaps(
        self, 
        full_text_length: int, 
        section_spans: Dict[str, Tuple[int, int]]
    ) -> List[Tuple[int, int]]:
        """
        Identify text ranges not covered by any section.
        
        Args:
            full_text_length: Length of the full document text
            section_spans: Dict mapping section names to (start, end) positions
            
        Returns:
            List of (start, end) tuples representing gaps
        """
        if not section_spans:
            return [(0, full_text_length)]
        
        # Sort intervals by start position
        intervals = sorted(section_spans.values(), key=lambda x: x[0])
        
        # Merge overlapping intervals
        merged = []
        for start, end in intervals:
            # Clamp to valid range
            start = max(0, start)
            end = min(full_text_length, end)
            
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        
        # Find gaps
        gaps = []
        prev_end = 0
        for start, end in merged:
            if start > prev_end:
                gaps.append((prev_end, start))
            prev_end = max(prev_end, end)
        
        # Trailing gap
        if prev_end < full_text_length:
            gaps.append((prev_end, full_text_length))
        
        return gaps


def create_chunker(
    chunk_size: int = 800,
    chunk_overlap: int = 150,
    min_chunk_size: int = 100
) -> HierarchicalChunker:
    """Factory function to create a chunker."""
    return HierarchicalChunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        min_chunk_size=min_chunk_size
    )
