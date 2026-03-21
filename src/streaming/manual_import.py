"""
SME Research Assistant - Manual PDF Import Scanner

Scans DataBase/ManualImport/ for user-provided PDFs and
registers them in the pipeline for processing.

Evidence:
- Reuses: src/utils/helpers.py:63-67 (generate_content_hash)
- Reuses: src/utils/apa_resolver.py:26-121 (construct_apa_from_dict)
- Reuses: src/storage/paper_store.py:105-144 (PaperStore.add_paper)
- Reuses: src/ingestion/pdf_parser.py:50-63 (PyMuPDFParser.validate)
"""

import hashlib
import logging
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

import fitz  # PyMuPDF

from ..storage.paper_store import PaperStore
from ..acquisition.paper_discoverer import DiscoveredPaper
from ..acquisition.api_clients.openalex import OpenAlexClient
from ..utils.apa_resolver import APAReferenceResolver
from ..ingestion.pdf_parser import PyMuPDFParser

logger = logging.getLogger(__name__)


@dataclass
class ManualImportResult:
    """Result of a manual import operation."""
    pdf_path: Path
    unique_id: str
    success: bool
    error: Optional[str] = None
    checksum: Optional[str] = None


class ManualImportScanner:
    """
    Scans a directory for PDFs and registers them for pipeline processing.

    Idempotency:
    - Uses SHA256 of file bytes as unique_id: "manual:<checksum>"
    - Prevents re-processing via DB UNIQUE constraint on unique_id

    File Lifecycle:
    - Input: DataBase/ManualImport/*.pdf
    - Success: -> DataBase/ManualImport/embedded/<filename>.pdf
    - Failure: -> DataBase/ManualImport/failed_parse/<filename>.pdf
    """

    UNIQUE_ID_PREFIX = "manual"

    def __init__(
        self,
        paper_store: PaperStore,
        import_dir: Path = Path("DataBase/ManualImport"),
        parser: Optional[PyMuPDFParser] = None
    ):
        self.paper_store = paper_store
        self.import_dir = Path(import_dir)
        self.parser = parser or PyMuPDFParser(quality_threshold=0.5)

        # Ensure directories exist
        self.embedded_dir = self.import_dir / "embedded"
        self.failed_dir = self.import_dir / "failed_parse"
        self.embedded_dir.mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(parents=True, exist_ok=True)

    def compute_file_checksum(self, file_path: Path) -> str:
        """
        Compute SHA256 checksum of file bytes.

        Evidence: Similar pattern in src/utils/helpers.py:63-67
        """
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def generate_unique_id(self, checksum: str) -> str:
        """
        Generate unique_id for manual imports.

        Format: "manual:<sha256_checksum>"

        Evidence: Follows pattern from src/acquisition/paper_discoverer.py:54-68
        """
        return f"{self.UNIQUE_ID_PREFIX}:{checksum}"

    def extract_metadata_from_pdf(self, pdf_path: Path) -> Dict[str, Any]:
        """
        Extract metadata from PDF using multi-tier extraction strategy.

        EXTRACTION METHODOLOGY:
        =======================

        Tier 1: PDF Document Metadata (XMP/Info Dict)
        - Source: fitz.Document.metadata (PyMuPDF built-in)
        - Fields: title, author, subject, keywords, creator, producer, creationDate
        - Reliability: HIGH for professionally published PDFs
        - Limitation: Often empty or generic for preprints/scans

        Tier 2: First Page Text Analysis
        - Source: First 3000 chars of page 1 text via fitz.Page.get_text()
        - Methods:
          a) Title: First substantial line (>20 chars, <200 chars, not header/footer)
          b) Authors: Lines after title matching author patterns (Name, Name, ...)
          c) Year: Regex for (20XX), (19XX), copyright patterns
          d) Abstract: Text between "Abstract" and "Introduction"/"Keywords"
        - Reliability: MEDIUM - works well for standard academic layouts

        Tier 3: Filename Parsing
        - Source: pdf_path.stem
        - Methods:
          a) DOI pattern: "10.XXXX_suffix" -> extract DOI for API lookup
          b) arXiv pattern: "arXiv-XXXX.XXXXX" or "2401.12345"
          c) Title fallback: Clean filename as title
        - Reliability: LOW but ensures non-empty title

        Returns dict compatible with DiscoveredPaper fields.

        Evidence: Reuses patterns from src/ingestion/pdf_parser.py:262-275 (_extract_title)
        """
        metadata = {
            "title": None,
            "authors": [],
            "year": None,
            "venue": None,
            "abstract": None,
            "extraction_confidence": "low",
            "extraction_sources": [],
        }

        # ═══════════════════════════════════════════════════════════
        # TIER 0: DOI API Lookup (Optional - for research articles)
        # ═══════════════════════════════════════════════════════════
        # Try DOI lookup first - but gracefully fall back for reports,
        # books, drafts, and other documents without DOI
        doi = (
            self._extract_doi_from_pdf_text(pdf_path) or
            self._extract_doi_from_filename(pdf_path.name)
        )
        if doi:
            api_metadata = self._lookup_doi_metadata(doi)
            if api_metadata:
                logger.info(f"[MANUAL-IMPORT] DOI lookup successful: {doi}")
                return api_metadata
            else:
                logger.debug(f"[MANUAL-IMPORT] DOI found but API lookup failed, using PDF extraction")

        # No DOI found OR API lookup failed → Continue with tier-based extraction
        # This handles: reports, books, drafts, articles without DOI, etc.

        try:
            doc = fitz.open(pdf_path)

            # ═══════════════════════════════════════════════════════════
            # TIER 1: PDF Document Metadata (XMP/Info Dictionary)
            # ═══════════════════════════════════════════════════════════
            pdf_meta = doc.metadata or {}

            # Title from metadata
            if pdf_meta.get("title") and len(pdf_meta["title"].strip()) > 5:
                title_candidate = pdf_meta["title"].strip()
                if not self._is_generic_title(title_candidate):
                    metadata["title"] = title_candidate
                    metadata["extraction_sources"].append("pdf_metadata:title")

            # Authors from metadata
            if pdf_meta.get("author"):
                authors_raw = pdf_meta["author"]
                parsed_authors = self._parse_author_string(authors_raw)
                if parsed_authors:
                    metadata["authors"] = parsed_authors
                    metadata["extraction_sources"].append("pdf_metadata:author")

            # Year from creation date
            if pdf_meta.get("creationDate"):
                year = self._extract_year_from_pdf_date(pdf_meta["creationDate"])
                if year:
                    metadata["year"] = year
                    metadata["extraction_sources"].append("pdf_metadata:creationDate")

            # Subject/Keywords as venue hint
            if pdf_meta.get("subject"):
                metadata["venue"] = pdf_meta["subject"][:100]
                metadata["extraction_sources"].append("pdf_metadata:subject")

            # ═══════════════════════════════════════════════════════════
            # TIER 2: First Page Text Analysis
            # ═══════════════════════════════════════════════════════════
            if doc.page_count > 0:
                first_page_text = doc[0].get_text()[:3000]

                # Title from first page (if not found in metadata)
                if not metadata["title"]:
                    title_from_text = self._extract_title_from_text(first_page_text)
                    if title_from_text:
                        metadata["title"] = title_from_text
                        metadata["extraction_sources"].append("text_analysis:title")

                # Authors from first page (if not found in metadata)
                if not metadata["authors"]:
                    authors_from_text = self._extract_authors_from_text(first_page_text)
                    if authors_from_text:
                        metadata["authors"] = authors_from_text
                        metadata["extraction_sources"].append("text_analysis:authors")

                # Year from first page text (if not found)
                if not metadata["year"]:
                    year_from_text = self._extract_year_from_text(first_page_text)
                    if year_from_text:
                        metadata["year"] = year_from_text
                        metadata["extraction_sources"].append("text_analysis:year")

                # Abstract extraction
                abstract = self._extract_abstract_from_text(first_page_text)
                if abstract:
                    metadata["abstract"] = abstract
                    metadata["extraction_sources"].append("text_analysis:abstract")

            doc.close()

            # ═══════════════════════════════════════════════════════════
            # TIER 3: Filename Parsing (Fallback)
            # ═══════════════════════════════════════════════════════════
            if not metadata["title"]:
                filename_title = self._clean_filename_as_title(pdf_path.stem)
                metadata["title"] = filename_title
                metadata["extraction_sources"].append("filename:title")

            # Calculate extraction confidence
            metadata["extraction_confidence"] = self._calculate_confidence(metadata)

        except Exception as e:
            logger.warning(f"Failed to extract PDF metadata from {pdf_path.name}: {e}")
            metadata["title"] = self._clean_filename_as_title(pdf_path.stem)
            metadata["extraction_sources"].append("filename:fallback")

        return metadata

    def _is_generic_title(self, title: str) -> bool:
        """Check if title is generic/useless."""
        generic_patterns = [
            "untitled", "document", "microsoft word", "adobe",
            "pdf", "scan", "page", "unknown", "temp",
            "contents lists available", "sciencedirect", "elsevier",
            "available online", "springer", "wiley"
        ]
        title_lower = title.lower()
        return any(p in title_lower for p in generic_patterns) or len(title) < 5

    def _parse_author_string(self, authors_raw: str) -> List[str]:
        """Parse author string into list of author names."""
        # Common separators: comma, semicolon, " and ", " & "
        if ";" in authors_raw:
            authors = [a.strip() for a in authors_raw.split(";")]
        elif " and " in authors_raw.lower():
            # Handle "A, B, and C" format
            authors_raw = re.sub(r',\s+and\s+', ', ', authors_raw, flags=re.IGNORECASE)
            authors_raw = re.sub(r'\s+and\s+', ', ', authors_raw, flags=re.IGNORECASE)
            authors = [a.strip() for a in authors_raw.split(",")]
        elif " & " in authors_raw:
            authors = [a.strip() for a in authors_raw.replace(" & ", ", ").split(",")]
        elif "," in authors_raw:
            # Tricky: could be "Last, First" or "Author1, Author2"
            parts = authors_raw.split(",")
            if len(parts) == 2 and len(parts[0].split()) == 1 and len(parts[1].split()) <= 2:
                # Likely "Last, First" format
                authors = [f"{parts[1].strip()} {parts[0].strip()}"]
            else:
                authors = [a.strip() for a in parts]
        else:
            authors = [authors_raw.strip()]

        # Filter empty and clean up
        return [a for a in authors if a and len(a) > 1]

    def _extract_year_from_pdf_date(self, date_str: str) -> Optional[int]:
        """Extract year from PDF date format (D:YYYYMMDDHHmmss)."""
        # PDF date format: D:YYYYMMDDHHmmss
        if date_str.startswith("D:") and len(date_str) >= 6:
            try:
                year = int(date_str[2:6])
                if 1900 <= year <= 2100:
                    return year
            except ValueError:
                pass

        # Try regex fallback
        match = re.search(r'(19|20)\d{2}', date_str)
        if match:
            return int(match.group(0))

        return None

    def _extract_title_from_text(self, text: str) -> Optional[str]:
        """
        Extract title from first page text.

        Strategy: Find first substantial line that's not a header/footer pattern.
        Evidence: Similar to src/ingestion/pdf_parser.py:262-275
        """
        lines = text.strip().split('\n')

        for line in lines[:15]:  # Check first 15 lines
            line = line.strip()

            # Skip if too short or too long
            if len(line) < 20 or len(line) > 300:
                continue

            # Skip common non-title patterns
            skip_patterns = [
                r'^(abstract|introduction|doi|volume|page|copyright|journal)',
                r'^\d+$',  # Just numbers
                r'^[a-z]{1,3}\d+',  # Citation-like
                r'^(received|accepted|published)',
                r'^(e-?mail|email|corresponding)',
            ]

            line_lower = line.lower()
            if any(re.match(p, line_lower) for p in skip_patterns):
                continue

            # Good candidate - return cleaned version
            # Remove markdown headers if present
            clean = re.sub(r'^#+\s*', '', line)
            return clean.strip()

        return None

    def _extract_authors_from_text(self, text: str) -> List[str]:
        """
        Extract authors from first page text.

        Strategy: Look for lines after title with name-like patterns.
        """
        lines = text.split('\n')
        authors = []

        for i, line in enumerate(lines[:20]):
            line = line.strip()

            # Skip short lines
            if len(line) < 5:
                continue

            # Check for author-like patterns
            # Names typically: "First Last", "F. Last", "First M. Last"
            name_pattern = r'^[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+'

            if re.match(name_pattern, line):
                # Might be author line - extract names
                # Split by common separators
                potential_authors = re.split(r'[,;]|\s+and\s+', line)
                for pa in potential_authors:
                    pa = pa.strip()
                    # Validate looks like a name (2-4 words, proper case)
                    words = pa.split()
                    if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
                        authors.append(pa)

        return authors[:10]  # Limit to 10 authors

    def _extract_year_from_text(self, text: str) -> Optional[int]:
        """Extract publication year from text."""
        current_year = datetime.now().year

        # Look for year patterns
        patterns = [
            r'\((\d{4})\)',  # (2023)
            r'©\s*(\d{4})',  # (C) 2023
            r'copyright\s+(\d{4})',  # Copyright 2023
            r'published[:\s]+(\d{4})',  # Published: 2023
            r'received[:\s]+.*?(\d{4})',  # Received: January 2023
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                year = int(match.group(1))
                if 1950 <= year <= current_year:
                    return year

        return None

    def _extract_abstract_from_text(self, text: str) -> Optional[str]:
        """
        Extract abstract from first page text.

        Evidence: Similar pattern to src/ingestion/pdf_parser.py:218-232
        """
        # Pattern: Text between "Abstract" and "Introduction"/"Keywords"
        abstract_pattern = r'abstract[:\s]*(.{50,2000}?)(?=introduction|keywords|background|1\.|1\s|$)'

        match = re.search(abstract_pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            abstract = match.group(1).strip()
            # Clean up
            abstract = re.sub(r'\s+', ' ', abstract)
            return abstract[:1500]  # Limit length

        return None

    def _clean_filename_as_title(self, filename: str) -> str:
        """Clean filename to use as title fallback."""
        clean = filename

        # Try to extract DOI and make it readable
        if clean.startswith("10."):
            # DOI format: 10.1234_suffix -> "DOI: 10.1234/suffix"
            parts = clean.split("_", 1)
            if len(parts) == 2:
                clean = f"{parts[0]}/{parts[1]}"
                return f"[DOI: {clean}]"

        # Remove underscores, dashes, clean up
        clean = re.sub(r'[_-]+', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean)

        return clean.strip() or "Untitled Document"

    def _calculate_confidence(self, metadata: Dict[str, Any]) -> str:
        """Calculate extraction confidence based on what was found."""
        sources = metadata.get("extraction_sources", [])

        # High confidence: multiple metadata sources + text analysis
        if len(sources) >= 4 and any("pdf_metadata" in s for s in sources):
            return "high"

        # Medium confidence: some structured data
        if len(sources) >= 2:
            return "medium"

        # Low confidence: mostly fallbacks
        return "low"

    # ═══════════════════════════════════════════════════════════════════
    # DOI/arXiv Extraction and API Lookup Methods
    # ═══════════════════════════════════════════════════════════════════

    def _extract_doi_from_pdf_text(self, pdf_path: Path, max_pages: int = 3) -> Optional[str]:
        """
        Extract DOI from PDF text content (first few pages).
        Returns None if no DOI found - this is normal for reports/books/drafts.
        """
        doi_pattern = r'(?:https?://(?:dx\.)?doi\.org/|doi[:\s]+)(10\.\d{4,}/[^\s\]>]+)'
        try:
            doc = fitz.open(pdf_path)
            for page_num in range(min(max_pages, doc.page_count)):
                text = doc[page_num].get_text()
                match = re.search(doi_pattern, text, re.IGNORECASE)
                if match:
                    doc.close()
                    return match.group(1).rstrip('.')
            doc.close()
        except Exception as e:
            logger.debug(f"DOI extraction from PDF text failed: {e}")
        return None

    def _extract_doi_from_filename(self, filename: str) -> Optional[str]:
        """
        Extract DOI from filename.
        Example: "10.1001_jama.2013.491.pdf" -> "10.1001/jama.2013.491"
        """
        name = filename.replace('.pdf', '').replace('.PDF', '')
        if name.startswith('10.'):
            parts = name.split('_', 1)
            if len(parts) == 2:
                doi = f"{parts[0]}/{parts[1]}"
                if re.match(r'^10\.\d{4,}/[^\s]+$', doi):
                    return doi
        return None

    def _extract_arxiv_id_from_filename(self, filename: str) -> Optional[str]:
        """
        Extract arXiv ID from filename.
        Patterns: arXiv-2301.12345.pdf or 2301.12345.pdf
        """
        name = filename.replace('.pdf', '').replace('.PDF', '')
        if name.startswith('arXiv-') or name.startswith('arxiv-'):
            arxiv_id = name[6:]
            if re.match(r'^\d{4}\.\d{4,5}(v\d+)?$', arxiv_id):
                return arxiv_id
        if re.match(r'^\d{4}\.\d{4,5}(v\d+)?$', name):
            return name
        return None

    def _lookup_doi_metadata(self, doi: str, email: str = "researcher@example.com") -> Optional[Dict[str, Any]]:
        """
        Look up complete metadata from OpenAlex API using DOI.
        Returns None if lookup fails - caller should fall back to tier extraction.
        """
        try:
            client = OpenAlexClient(email=email)
            paper = client.get_paper_by_doi(doi)
            client.close()
            if paper:
                return {
                    "title": paper.title,
                    "authors": paper.authors,
                    "year": paper.year,
                    "venue": paper.venue,
                    "abstract": paper.abstract,
                    "doi": paper.doi,
                    "citation_count": paper.citation_count,
                    "extraction_confidence": "high",
                    "extraction_sources": ["api:openalex"],
                }
        except Exception as e:
            logger.debug(f"DOI lookup failed for {doi}: {e}")
        return None

    def construct_apa_reference(self, metadata: Dict[str, Any]) -> str:
        """
        Construct APA reference from extracted metadata.

        Evidence: Reuses src/utils/apa_resolver.py:26-121
        """
        return APAReferenceResolver.construct_apa_from_dict(metadata)

    def check_already_processed(self, unique_id: str) -> bool:
        """Check if this file was already processed (exists in DB)."""
        return self.paper_store.status_exists(unique_id)

    def register_paper(
        self,
        pdf_path: Path,
        checksum: str,
        metadata: Dict[str, Any],
        apa_reference: str
    ) -> bool:
        """
        Register paper in database with status='downloaded'.

        Evidence: Uses PaperStore.add_paper() from src/storage/paper_store.py:105-144
        """
        unique_id = self.generate_unique_id(checksum)

        paper = DiscoveredPaper(
            doi=metadata.get("doi"),
            arxiv_id=metadata.get("arxiv_id"),
            openalex_id=None,
            title=metadata.get("title", pdf_path.stem),
            authors=metadata.get("authors", []),
            year=metadata.get("year"),
            venue=metadata.get("venue"),
            abstract=metadata.get("abstract"),
            pdf_url=None,
            open_access=True,
            citation_count=0,
            source="manual_import",
            status="downloaded",  # Ready for pipeline processing
            pdf_path=str(pdf_path),
            chunk_file=None,
            metadata={
                "file_checksum": checksum,
                "import_source": "manual",
                "original_filename": pdf_path.name,
                "extraction_confidence": metadata.get("extraction_confidence", "low"),
                "extraction_sources": metadata.get("extraction_sources", []),
            },
            apa_reference=apa_reference,
            file_checksum=checksum,
            import_source="manual_import"
        )

        return self.paper_store.add_paper(paper)

    def scan_and_register(self, max_workers: int = 4) -> List[ManualImportResult]:
        """
        Main entry point: scan directory and register all new PDFs.

        Uses parallel processing for improved performance on large imports.

        Args:
            max_workers: Number of parallel workers (default 4)

        Returns list of results for each PDF processed.
        """
        results = []

        if not self.import_dir.exists():
            logger.info(f"[MANUAL-IMPORT] Directory does not exist: {self.import_dir}")
            self.import_dir.mkdir(parents=True, exist_ok=True)
            return results

        pdf_files = list(self.import_dir.glob("*.pdf"))
        logger.info(f"[MANUAL-IMPORT] Found {len(pdf_files)} PDFs in {self.import_dir} (workers={max_workers})")

        if not pdf_files:
            return results

        # Use ThreadPoolExecutor for parallel processing
        # Checksum is I/O-bound, metadata extraction can benefit from parallelism
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_pdf = {executor.submit(self._process_single_pdf, pdf): pdf for pdf in pdf_files}
            for future in as_completed(future_to_pdf):
                pdf_path = future_to_pdf[future]
                try:
                    result = future.result()
                    results.append(result)

                    if result.success:
                        logger.info(f"[MANUAL-IMPORT] Registered: {pdf_path.name} -> {result.unique_id}")
                    else:
                        logger.warning(f"[MANUAL-IMPORT] Skipped: {pdf_path.name} - {result.error}")
                except Exception as e:
                    logger.error(f"[MANUAL-IMPORT] Worker error for {pdf_path.name}: {e}")
                    results.append(ManualImportResult(
                        pdf_path=pdf_path,
                        unique_id="",
                        success=False,
                        error=str(e)
                    ))

        return results

    def retry_failed_parses(self, max_workers: int = 2) -> List[ManualImportResult]:
        """
        Retry processing PDFs from failed_parse directory.

        Uses lower worker count since these are known difficult PDFs.

        Returns list of results for each PDF retried.
        """
        results = []

        failed_dir = self.import_dir / "failed_parse"
        if not failed_dir.exists():
            return results

        pdf_files = list(failed_dir.glob("*.pdf"))
        logger.info(f"[MANUAL-IMPORT] Retrying {len(pdf_files)} failed PDFs (workers={max_workers})")

        if not pdf_files:
            return results

        # Move PDFs back to root directory for processing
        for pdf_path in pdf_files:
            try:
                dest = self.import_dir / pdf_path.name
                # Handle collision
                counter = 1
                while dest.exists():
                    dest = self.import_dir / f"{pdf_path.stem}_retry{counter}{pdf_path.suffix}"
                    counter += 1

                shutil.move(str(pdf_path), str(dest))
                logger.info(f"[MANUAL-IMPORT] Moved for retry: {pdf_path.name}")
            except Exception as e:
                logger.error(f"[MANUAL-IMPORT] Failed to move {pdf_path.name} for retry: {e}")

        # Now scan and register normally (they'll be in root directory)
        return self.scan_and_register(max_workers=max_workers)

    def _process_single_pdf(self, pdf_path: Path) -> ManualImportResult:
        """Process a single PDF file with optimized de-duplication."""
        try:
            # 1. Compute checksum (fast)
            checksum = self.compute_file_checksum(pdf_path)

            # 2. Check for existing record by Checksum (fast DB lookup)
            existing = self.paper_store.find_by_checksum(checksum)
            if existing:
                if existing.status == 'embedded':
                    move_to_embedded(pdf_path, self.embedded_dir)
                    return ManualImportResult(
                        pdf_path=pdf_path,
                        unique_id=existing.unique_id,
                        success=False,
                        error="Already embedded (moved to embedded folder)",
                        checksum=checksum
                    )
                else:
                    self.paper_store.upgrade_to_manual_import(existing.unique_id, str(pdf_path), checksum)
                    return ManualImportResult(
                        pdf_path=pdf_path,
                        unique_id=existing.unique_id,
                        success=True,
                        checksum=checksum
                    )

            # 3. Quick DOI check from filename (no PDF parsing yet)
            quick_doi = self._extract_doi_from_filename(pdf_path.name)
            if quick_doi:
                existing = self.paper_store.find_by_doi(quick_doi)
                if existing:
                    if existing.status == 'embedded':
                        move_to_embedded(pdf_path, self.embedded_dir)
                        return ManualImportResult(
                            pdf_path=pdf_path,
                            unique_id=existing.unique_id,
                            success=False,
                            error=f"DOI already embedded (ID: {existing.unique_id})",
                            checksum=checksum
                        )
                    else:
                        logger.info(f"[MANUAL-IMPORT] Found existing DOI record: {existing.unique_id}. Upgrading.")
                        self.paper_store.upgrade_to_manual_import(existing.unique_id, str(pdf_path), checksum)
                        return ManualImportResult(
                            pdf_path=pdf_path,
                            unique_id=existing.unique_id,
                            success=True,
                            checksum=checksum
                        )

            # 4. Validate PDF format before expensive metadata extraction
            if not self.parser.validate(pdf_path):
                self._move_to_failed(pdf_path, "Invalid PDF format")
                return ManualImportResult(
                    pdf_path=pdf_path,
                    unique_id="",
                    success=False,
                    error="Invalid PDF format",
                    checksum=checksum
                )

            # 5. Full metadata extraction (API lookup or PDF parsing)
            metadata = self.extract_metadata_from_pdf(pdf_path)

            # 6. Check by DOI (if found from PDF text, different from filename)
            doi = metadata.get('doi')
            if doi and doi != quick_doi:
                existing = self.paper_store.find_by_doi(doi)
                if existing:
                    if existing.status == 'embedded':
                        move_to_embedded(pdf_path, self.embedded_dir)
                        return ManualImportResult(
                            pdf_path=pdf_path,
                            unique_id=existing.unique_id,
                            success=False,
                            error=f"DOI already embedded (ID: {existing.unique_id})",
                            checksum=checksum
                        )
                    else:
                        logger.info(f"[MANUAL-IMPORT] Found existing DOI record: {existing.unique_id}. Upgrading.")
                        self.paper_store.upgrade_to_manual_import(existing.unique_id, str(pdf_path), checksum)
                        return ManualImportResult(
                            pdf_path=pdf_path,
                            unique_id=existing.unique_id,
                            success=True,
                            checksum=checksum
                        )

            # 7. Check by Title
            title = metadata.get('title')
            if title:
                existing = self.paper_store.find_by_title(title)
                if existing:
                    if existing.status == 'embedded':
                        move_to_embedded(pdf_path, self.embedded_dir)
                        return ManualImportResult(
                            pdf_path=pdf_path,
                            unique_id=existing.unique_id,
                            success=False,
                            error=f"Title already embedded (ID: {existing.unique_id})",
                            checksum=checksum
                        )
                    else:
                        logger.info(f"[MANUAL-IMPORT] Found existing title record: {existing.unique_id}. Upgrading.")
                        self.paper_store.upgrade_to_manual_import(existing.unique_id, str(pdf_path), checksum)
                        return ManualImportResult(
                            pdf_path=pdf_path,
                            unique_id=existing.unique_id,
                            success=True,
                            checksum=checksum
                        )

            # 8. Construct APA reference
            apa_reference = self.construct_apa_reference(metadata)

            # 9. Register brand new paper in database
            added = self.register_paper(pdf_path, checksum, metadata, apa_reference)

            if added:
                # Need to get the unique_id back (manual:checksum)
                unique_id = self.generate_unique_id(checksum)
                return ManualImportResult(
                    pdf_path=pdf_path,
                    unique_id=unique_id,
                    success=True,
                    checksum=checksum
                )
            else:
                return ManualImportResult(
                    pdf_path=pdf_path,
                    unique_id="",
                    success=False,
                    error="Failed to insert into database (unknown error)",
                    checksum=checksum
                )

        except Exception as e:
            logger.error(f"[MANUAL-IMPORT] Error processing {pdf_path.name}: {e}")
            return ManualImportResult(
                pdf_path=pdf_path,
                unique_id="",
                success=False,
                error=str(e)
            )

    def _move_to_failed(self, pdf_path: Path, reason: str):
        """Move invalid PDF to failed directory."""
        try:
            dest = self.failed_dir / pdf_path.name
            # Handle naming collision
            counter = 1
            while dest.exists():
                dest = self.failed_dir / f"{pdf_path.stem}_{counter}{pdf_path.suffix}"
                counter += 1
            shutil.move(str(pdf_path), str(dest))
            logger.info(f"[MANUAL-IMPORT] Moved to failed: {pdf_path.name} ({reason})")
        except Exception as e:
            logger.error(f"[MANUAL-IMPORT] Failed to move {pdf_path.name} to failed dir: {e}")


def move_to_embedded(pdf_path: Path, embedded_dir: Path) -> bool:
    """
    Move successfully embedded PDF to embedded directory.
    Called from on_success callback in autonomous_update.py.

    Uses shutil.move() for cross-filesystem compatibility.
    """
    try:
        embedded_dir.mkdir(parents=True, exist_ok=True)
        dest = embedded_dir / Path(pdf_path).name

        # Handle naming collision
        counter = 1
        while dest.exists():
            stem = Path(pdf_path).stem
            suffix = Path(pdf_path).suffix
            dest = embedded_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        shutil.move(str(pdf_path), str(dest))
        logger.info(f"[MANUAL-IMPORT] Moved to embedded: {Path(pdf_path).name}")
        return True
    except Exception as e:
        logger.error(f"[MANUAL-IMPORT] Failed to move to embedded: {e}")
        return False


def move_to_failed_parse(pdf_path: Path, failed_dir: Path) -> bool:
    """
    Move parse-failed PDF to failed_parse directory.
    Called from DLQ handler or chunk stage error handler.
    """
    try:
        failed_dir.mkdir(parents=True, exist_ok=True)
        dest = failed_dir / Path(pdf_path).name

        # Handle naming collision
        counter = 1
        while dest.exists():
            stem = Path(pdf_path).stem
            suffix = Path(pdf_path).suffix
            dest = failed_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        shutil.move(str(pdf_path), str(dest))
        logger.info(f"[MANUAL-IMPORT] Moved to failed_parse: {Path(pdf_path).name}")
        return True
    except Exception as e:
        logger.error(f"[MANUAL-IMPORT] Failed to move to failed_parse: {e}")
        return False
