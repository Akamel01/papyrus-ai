"""
SME Research Assistant - Paper Discoverer

Coordinates paper discovery across multiple academic APIs
with deduplication and prioritization.

Features:
- Multi-source search (OpenAlex, Semantic Scholar, arXiv)
- DOI-based deduplication
- Filtering against existing papers
- Result ranking by relevance and citation count
"""

import logging
from typing import List, Dict, Any, Optional, Set, Iterator
from dataclasses import dataclass, field
from pathlib import Path
import re

from .api_clients.openalex import OpenAlexClient, PaperMetadata
from .api_clients.semantic_scholar import SemanticScholarClient, S2PaperMetadata
from .api_clients.arxiv_client import ArxivClient, ArxivPaperMetadata
from .api_clients.arxiv_client import ArxivClient, ArxivPaperMetadata
from .api_clients.crossref import CrossrefClient
from ..utils.apa_resolver import APAReferenceResolver

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredPaper:
    """Unified paper metadata from any source."""
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    openalex_id: Optional[str] = None  # OpenAlex work ID (e.g., W12345)
    title: str = ""
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    pdf_url: Optional[str] = None
    open_access: bool = False
    citation_count: int = 0
    source: str = ""
    # Status tracking
    status: str = "discovered"  # discovered, downloaded, chunked, embedded
    pdf_path: Optional[str] = None
    chunk_file: Optional[str] = None
    # Rich metadata (volume, issue, pages, etc.)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Citation String
    apa_reference: Optional[str] = None
    # Manual Import tracking
    file_checksum: Optional[str] = None
    import_source: str = "api"  # api, manual_import
    # Multi-user support
    user_id: Optional[str] = None  # None = shared KB, string = user's personal document

    @property
    def unique_id(self) -> str:
        """Get unique identifier for deduplication."""
        # User documents: prefix with user_id for isolation
        if self.user_id:
            if self.file_checksum:
                return f"user:{self.user_id}:manual:{self.file_checksum}"
            return f"user:{self.user_id}:title:{self._normalize_title(self.title)}"
        # Prioritize manual checksum if it's a manual import (shared KB)
        if self.file_checksum and self.import_source == "manual_import":
            return f"manual:{self.file_checksum}"
        if self.doi:
            return f"doi:{self.doi.lower()}"
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id.lower()}"
        return f"title:{self._normalize_title(self.title)}"
    
    def _normalize_title(self, title: str) -> str:
        """Normalize title for comparison."""
        title = title.lower()
        title = re.sub(r'[^\w\s]', '', title)
        title = ' '.join(title.split())
        return title
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "openalex_id": self.openalex_id,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "abstract": self.abstract,
            "pdf_url": self.pdf_url,
            "open_access": self.open_access,
            "citation_count": self.citation_count,
            "source": self.source,
            "status": self.status,
            "pdf_path": self.pdf_path,
            "chunk_file": self.chunk_file,
            "metadata": self.metadata,
            "user_id": self.user_id,
        }

    def merge(self, other: 'DiscoveredPaper'):
        """
        Merge another paper entry into this one (Smart Merge).
        Only updates fields if the other paper has better data.
        """
        # 1. Update IDs if missing
        if not self.doi and other.doi: self.doi = other.doi
        if not self.arxiv_id and other.arxiv_id: self.arxiv_id = other.arxiv_id
        if not self.openalex_id and other.openalex_id: self.openalex_id = other.openalex_id
        
        # 2. Update Abstract (Crucial: Don't overwrite existing abstract with empty/short one)
        # Strategy: Keep the longer abstract
        if other.abstract:
            if not self.abstract or len(other.abstract) > len(self.abstract):
                self.abstract = other.abstract
        
        # 3. Update Citation Count (Take Max)
        if other.citation_count > self.citation_count:
            self.citation_count = other.citation_count
            
        # 4. Update PDF URL (Prefer Open Access / Direct)
        if not self.pdf_url and other.pdf_url:
            self.pdf_url = other.pdf_url
            
        # 5. Authors (Union if we barely have any)
        if not self.authors and other.authors:
            self.authors = other.authors
        
        # 6. Source tracking (Append source if new)
        if other.source not in self.source:
             self.source += f"|{other.source}"


class PaperDiscoverer:
    """
    Coordinates paper discovery across multiple academic APIs.
    
    Searches multiple sources, deduplicates results, and filters
    against existing papers in the database.
    
    Features:
    - Multi-email rotation for rate limit handling
    - Comprehensive error handling with fallback
    - Deduplication across sources
    """
    
    def __init__(
        self,
        email: Optional[str] = None,
        emails: Optional[List[str]] = None,
        semantic_scholar_api_key: Optional[str] = None,
        enable_openalex: bool = True,
        enable_semantic_scholar: bool = True,
        enable_arxiv: bool = True,
        enable_crossref: bool = True,
        papers_dir: Optional[Path] = None
    ):
        """
        Initialize paper discoverer.
        
        Args:
            email: Single email for API polite pools (legacy)
            emails: List of emails for rotation (preferred)
            semantic_scholar_api_key: Optional API key for Semantic Scholar
            enable_openalex: Enable OpenAlex API
            enable_semantic_scholar: Enable Semantic Scholar API
            enable_arxiv: Enable arXiv API
            enable_crossref: Enable Crossref API
            papers_dir: Directory containing existing papers (for deduplication)
        """
        # Internal Vocabulary Mapping
        # KEYS: Config/Internal Types (snake_case)
        # VALUES: Tuple(OpenAlex, Crossref, SemanticScholar)
        self._type_mapping = {
            "journal_article": (
                {"type": "article", "primary_location.source.type": "journal"},
                "journal-article",
                "JournalArticle"
            ),
            "conference_paper": (
                {"type": "conference-proceedings"},
                "proceedings-article",
                "Conference"
            ),
            "preprint": (
                {"type": "preprint"},
                "posted-content",
                "Preprint"
            ),
            "book": (
                {"type": "book"},
                "book",
                "Book"
            ),
            "book_chapter": (
                {"type": "book-chapter"},
                "book-chapter",
                "BookChapter"
            ),
            "review": (
                {"type": "review"},
                "journal-article",  # Crossref lacks specific review type, mostly journal-article
                "Review"
            ),
            "report": (
                {"type": "report"},
                "report",
                None  # S2 has no report type
            ),
            "dataset": (
                {"type": "dataset"},
                "dataset",
                None  # S2 has no dataset type
            ),
            "editorial": (
                {"type": "editorial"},
                "journal-article", # Fallback
                "Editorial"
            ),
            "thesis": (
                ["dissertation", "thesis"], # OpenAlex has both
                "dissertation",
                None
            ),
            "clinical_trial": (
                None, # OpenAlex lacks specific type
                None,
                "ClinicalTrial"
            ),
            "letter": (
                {"type": "letter"},
                "journal-article", # Fallback
                "LettersAndComments"
            ),
            "standard": (
                {"type": "standard"},
                "standard",
                None
            )
        }
        # Support both single email and list
        if emails:
            self.emails = emails
        elif email:
            self.emails = [email]
        else:
            self.emails = []
        
        # Legacy papers_dir support (optional, can be ignored if existing_ids provided)
        self.papers_dir = papers_dir or Path("DataBase/Papers")
        
        # Initialize enabled clients
        self.clients = {}
        
        if enable_openalex:
            self.clients["openalex"] = OpenAlexClient(
                emails=self.emails,
                requests_per_minute=60
            )
        
        if enable_semantic_scholar:
            self.clients["semantic_scholar"] = SemanticScholarClient(
                api_key=semantic_scholar_api_key,
                requests_per_minute=10
            )
        
        if enable_arxiv:
            self.clients["arxiv"] = ArxivClient(
                requests_per_minute=20
            )

        if enable_crossref:
            self.clients["crossref"] = CrossrefClient(
                emails=self.emails,
                requests_per_minute=50
            )
        
        
        logger.info(f"Initialized PaperDiscoverer with clients: {list(self.clients.keys())}")
    
    def discover(
        self,
        keywords: List[str],
        filters: Optional[Dict[str, Any]] = None,
        max_per_keyword: int = 500,
        max_total: int = 5000,
        exclude_existing: bool = True,
        existing_ids: Optional[Set[str]] = None
    ) -> List[DiscoveredPaper]:
        """
        Discover papers matching keywords.
        
        Args:
            keywords: List of search keywords
            filters: Optional filters (year, open_access, from_updated_date)
            max_per_keyword: Maximum papers per keyword
            max_total: Maximum total papers to return
            exclude_existing: Exclude papers already in database
            existing_ids: Optional set of existing unique_ids (optimization)
            
        Returns:
            List of DiscoveredPaper objects
        """
        filters = filters or {}
        all_papers: Dict[str, DiscoveredPaper] = {}  # unique_id -> paper
        
        # Get existing IDs for deduplication
        if exclude_existing:
            # Start with provided DB IDs (if any)
            ids_to_exclude = set(existing_ids) if existing_ids else set()
            
            # ALWAYS merge with legacy filesystem scan to ensure checking against 52,623+ files
            # This ensures we don't redownload papers that exist on disk but aren't in DB yet
            filesystem_ids = self._get_existing_paper_ids()
            ids_to_exclude.update(filesystem_ids)
            
            existing_ids = ids_to_exclude
            logger.info(f"Deduplicating against {len(existing_ids)} papers (DB + Filesystem)")
        else:
            existing_ids = set()
        
        for keyword in keywords:
            logger.info(f"Searching for: '{keyword}'")
            
            # Search each enabled source
            for source_name, client in self.clients.items():
                try:
                    papers = self._search_source(
                        source_name,
                        client,
                        keyword,
                        filters,
                        max_per_keyword
                    )
                    
                    # Add to results with deduplication
                    for paper in papers:
                        unique_id = paper.unique_id
                        
                        # Skip if already in existing database
                        if exclude_existing and self._is_existing(paper, existing_ids):
                            continue
                        
                        # Skip if already discovered (Smart Merge)
                        if unique_id in all_papers:
                            existing = all_papers[unique_id]
                            # MERGE instead of replace
                            existing.merge(paper)
                        else:
                            all_papers[unique_id] = paper
                    
                    logger.debug(f"Found {len(papers)} papers from {source_name} for '{keyword}'")
                    
                except Exception as e:
                    logger.error(f"Error searching {source_name} for '{keyword}': {e}")
                    continue
        
        # Sort by citation count (most cited first) and limit
        results = sorted(
            all_papers.values(),
            key=lambda p: (p.citation_count or 0, p.year or 0),
            reverse=True
        )[:max_total]
        
        logger.info(f"Discovered {len(results)} unique papers (after deduplication)")
        return results
    
    def discover_stream(
        self,
        keywords: List[str],
        filters: Optional[Dict[str, Any]] = None,
        max_per_keyword: int = 500,
        exclude_existing: bool = True
    ) -> Iterator[DiscoveredPaper]:
        """
        Stream papers matching keywords (memory-efficient generator).
        
        Yields papers as they are discovered, suitable for 100K+ scale.
        Does not load all papers into memory at once.
        
        Args:
            keywords: List of search keywords
            filters: Optional filters (year, open_access, etc.)
            max_per_keyword: Maximum papers per keyword
            exclude_existing: Exclude papers already in database
            
        Yields:
            DiscoveredPaper objects
        """
        from typing import Iterator
        
        filters = filters or {}
        seen_ids: set = set()
        
        # Get existing DOIs for deduplication
        existing_ids = set()
        if exclude_existing:
            existing_ids = self._get_existing_paper_ids()
            logger.info(f"Found {len(existing_ids)} existing papers to exclude")
        
        for keyword in keywords:
            logger.info(f"Streaming results for: '{keyword}'")
            
            # Search each enabled source
            for source_name, client in self.clients.items():
                try:
                    # Use streaming source if possible
                    iterator = self._stream_source(
                        source_name,
                        client,
                        keyword,
                        filters,
                        max_per_keyword
                    )
                    
                    for paper in iterator:
                        unique_id = paper.unique_id
                        
                        # Skip duplicates
                        if unique_id in seen_ids:
                            continue
                        
                        # Skip if already in existing database
                        if exclude_existing and self._is_existing(paper, existing_ids):
                            continue
                        
                        seen_ids.add(unique_id)
                        yield paper
                        
                except Exception as e:
                    logger.error(f"Error searching {source_name} for '{keyword}': {e}")
                    continue
        
        logger.info(f"Streamed {len(seen_ids)} unique papers")
    
    def _stream_source(
        self,
        source_name: str,
        client: Any,
        keyword: str,
        filters: Dict[str, Any],
        max_results: int
    ) -> Iterator[DiscoveredPaper]:
        """Stream papers from a single source."""
        
        # 1. Map Publication Types to Source Vocabulary (Same concept as _search_source)
        source_filters = filters.copy()
        if "publication_types" in filters:
            internal_types = filters["publication_types"]
            mapped_types = self._map_publication_types(source_name, internal_types)
            source_filters["publication_types"] = mapped_types
            
            # OpenAlex specific handling
            if source_name == "openalex":
                 oa_types = []
                 for t_def in mapped_types:
                     if isinstance(t_def, dict):
                         oa_types.append(t_def["type"])
                 source_filters["publication_types"] = oa_types

            # Arxiv Optimization: Skip if searching for types NOT supported by Arxiv
            # Arxiv mainly covers preprints and journal usage.
            # If user is searching ONLY for 'book', 'dataset', etc., skip Arxiv.
            if source_name == "arxiv":
                # Arxiv "Supported" logical types
                ARXIV_COMPATIBLE = {"preprint", "journal_article", "review", "conference_paper"}
                
                # Check intersection
                requested_set = set(internal_types)
                if not requested_set.intersection(ARXIV_COMPATIBLE):
                    logger.debug(f"Skipping arXiv for incompatible types: {internal_types}")
                    return # Yield nothing
        
        # 2. Select Method
        search_method = getattr(client, "search_papers_generator", client.search_papers)
        
        try:
            results_iter = search_method(
                query=keyword,
                filters=source_filters,
                max_results=max_results
            )
            
            for r in results_iter:
                if source_name == "openalex":
                    yield self._from_openalex(r)
                elif source_name == "semantic_scholar":
                    yield self._from_semantic_scholar(r)
                elif source_name == "arxiv":
                    yield self._from_arxiv(r)
                elif source_name == "crossref":
                    yield self._from_crossref(r)
        except Exception as e:
            logger.error(f"Stream error in {source_name}: {e}")
            raise e
    
    def _search_source(
        self,
        source_name: str,
        client: Any,
        keyword: str,
        filters: Dict[str, Any],
        max_results: int
    ) -> List[DiscoveredPaper]:
        """Search a single source and convert to DiscoveredPaper."""
        papers = []
        
        # 1. Map Publication Types to Source Vocabulary
        source_filters = filters.copy()
        if "publication_types" in filters:
            internal_types = filters["publication_types"]
            mapped_types = self._map_publication_types(source_name, internal_types)
            source_filters["publication_types"] = mapped_types
            
            # OpenAlex specific handling for complex filters (type + location)
            if source_name == "openalex":
                # _map_publication_types returns list of dicts for OA
                # We need to flatten/merge this for the client if possible
                # The generic client usually takes a list of strings for 'type'
                # But here we have strict requirements.
                # For now, we will extract just the 'type' field strings to be compatible 
                # with existing client logic, OR pass the dicts if client supports it.
                # Existing client expects strings. Let's extract 'type' values.
                # TODO: Update client to support complex location filters if needed.
                # For this implementation, we take the 'type' value.
                 oa_types = []
                 for t_def in mapped_types:
                     if isinstance(t_def, dict):
                         oa_types.append(t_def["type"])
                 source_filters["publication_types"] = oa_types

        
        if source_name == "openalex":
            results = client.search_papers(
                query=keyword,
                filters=source_filters,
                max_results=max_results
            )
            for r in results:
                papers.append(self._from_openalex(r))
                
        elif source_name == "semantic_scholar":
            results = client.search_papers(
                query=keyword,
                filters=source_filters,
                max_results=max_results
            )
            for r in results:
                papers.append(self._from_semantic_scholar(r))
                
        elif source_name == "arxiv":
             # arXiv does NOT use publication types. Explicitly remove.
            if "publication_types" in source_filters:
                del source_filters["publication_types"]
                
            results = client.search_papers(
                query=keyword,
                filters=source_filters,
                max_results=max_results
            )
            for r in results:
                papers.append(self._from_arxiv(r))

        elif source_name == "crossref":
            results = client.search_papers(
                query=keyword,
                filters=source_filters, # Passed as journal-article, etc.
                max_results=max_results
            )
            for r in results:
                papers.append(self._from_crossref(r))
        
        return papers

    def _map_publication_types(self, source: str, internal_types: List[str]) -> List[Any]:
        """
        Translate internal publication types to source-specific vocabulary.
        Raises ValueError if an internal type is unknown.
        """
        if not internal_types:
            return []
            
        mapped = []
        for itype in internal_types:
            if itype not in self._type_mapping:
                # FAIL LOUDLY
                raise ValueError(
                    f"❌ Invalid publication type: '{itype}'. "
                    f"Allowed types: {list(self._type_mapping.keys())}"
                )
            
            mapping = self._type_mapping[itype]
            
            if source == "openalex":
                mapped.append(mapping[0])
            elif source == "crossref":
                mapped.append(mapping[1])
            elif source == "semantic_scholar":
                mapped.append(mapping[2])
            # arXiv handled separately (ignored)
        
        return mapped
    
    def _from_openalex(self, paper: PaperMetadata) -> DiscoveredPaper:
        """Convert OpenAlex paper to DiscoveredPaper."""
        # Extract rich metadata from raw OpenAlex data
        raw = paper.raw_data
        biblio = raw.get("biblio", {})
        
        meta = {
            "volume": biblio.get("volume"),
            "issue": biblio.get("issue"),
            "pages": f"{biblio.get('first_page')}-{biblio.get('last_page')}" if biblio.get('first_page') else None,
            "enrichment_source": "openalex"
        }
        
        # Clean up None values
        meta = {k: v for k, v in meta.items() if v}

        # Generate APA Reference
        apa_ref = APAReferenceResolver.construct_apa_from_dict({
            "title": paper.title,
            "authors": paper.authors, 
            "year": paper.year,
            "venue": paper.venue,
            "doi": paper.doi,
            "pdf_url": paper.pdf_url,
            "metadata": meta
        })

        return DiscoveredPaper(
            doi=paper.doi,
            title=paper.title,
            openalex_id=paper.openalex_id,
            authors=paper.authors,
            year=paper.year,
            venue=paper.venue,
            abstract=paper.abstract,
            pdf_url=paper.pdf_url,
            open_access=paper.open_access,
            citation_count=paper.citation_count,
            source="openalex",
            metadata=meta,
            apa_reference=apa_ref
        )
    
    def _from_semantic_scholar(self, paper: S2PaperMetadata) -> DiscoveredPaper:
        """Convert Semantic Scholar paper to DiscoveredPaper."""
        apa_ref = APAReferenceResolver.construct_apa_from_dict({
            "title": paper.title,
            "authors": paper.authors,
            "year": paper.year,
            "venue": paper.venue,
            "doi": paper.doi,
            "pdf_url": paper.pdf_url
        })
        
        return DiscoveredPaper(
            doi=paper.doi,
            title=paper.title or "",
            authors=paper.authors,
            year=paper.year,
            venue=paper.venue,
            abstract=paper.abstract,
            pdf_url=paper.pdf_url,
            open_access=paper.open_access,
            citation_count=paper.citation_count,
            source="semantic_scholar",
            apa_reference=apa_ref
        )
    
    def _from_arxiv(self, paper: ArxivPaperMetadata) -> DiscoveredPaper:
        """Convert arXiv paper to DiscoveredPaper."""
        apa_ref = APAReferenceResolver.construct_apa_from_dict({
            "title": paper.title or "",
            "authors": paper.authors,
            "year": paper.year,
            "doi": paper.doi,
            "pdf_url": paper.pdf_url,
            # Arxiv has no venue usually
        })
        
        return DiscoveredPaper(
            doi=paper.doi,
            arxiv_id=paper.arxiv_id,
            title=paper.title or "",
            authors=paper.authors,
            year=paper.year,
            abstract=paper.abstract,
            pdf_url=paper.pdf_url,
            open_access=True,  # arXiv is always open access
            citation_count=0,  # arXiv doesn't provide citation counts
            source="arxiv",
            apa_reference=apa_ref
        )

    def _from_crossref(self, paper: PaperMetadata) -> DiscoveredPaper:
        """Convert Crossref paper to DiscoveredPaper."""
        meta = {"enrichment_source": "crossref"}
        apa_ref = APAReferenceResolver.construct_apa_from_dict({
            "title": paper.title or "",
            "authors": paper.authors,
            "year": paper.year,
            "venue": paper.venue,
            "doi": paper.doi,
            "metadata": meta
        })

        return DiscoveredPaper(
            doi=paper.doi,
            title=paper.title or "",
            authors=paper.authors,
            year=paper.year,
            venue=paper.venue,
            abstract=paper.abstract,
            pdf_url=None, # Crossref PDFs are hard to direct link
            open_access=False,
            citation_count=paper.citation_count,
            source="crossref",
            metadata=meta,
            apa_reference=apa_ref
        )
    
    def _get_existing_paper_ids(self) -> Set[str]:
        """Get set of existing paper identifiers from database."""
        existing = set()
        
        if not self.papers_dir.exists():
            return existing
        
        for pdf_file in self.papers_dir.glob("*.pdf"):
            filename = pdf_file.stem
            # Normalize - underscores may represent slashes in DOI
            doi = filename.replace("_", "/")
            existing.add(f"doi:{doi.lower()}")
            
            # Also add arxiv-style IDs
            if filename.startswith("arXiv-"):
                arxiv_id = filename.replace("arXiv-", "")
                existing.add(f"arxiv:{arxiv_id.lower()}")
        return existing
    
    def _is_existing(self, paper: DiscoveredPaper, existing_ids: Set[str]) -> bool:
        """Check if paper already exists (in provided set)."""
        return paper.unique_id in existing_ids

    
    def close(self):
        """Close all API clients."""
        for client in self.clients.values():
            if hasattr(client, 'close'):
                client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
