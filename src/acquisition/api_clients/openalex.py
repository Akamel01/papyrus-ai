"""
SME Research Assistant - OpenAlex API Client

OpenAlex is a comprehensive open catalog of scholarly papers, authors, and institutions.
https://docs.openalex.org/

Features:
- Keyword-based paper search
- Filters by year, publication type, open access
- Returns DOIs, metadata, and open access URLs
"""

import logging
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
import requests
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


@dataclass
class PaperMetadata:
    """Represents metadata for a discovered paper."""
    doi: str
    title: str
    openalex_id: Optional[str] = None  # OpenAlex work ID (e.g., W12345)
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    pdf_url: Optional[str] = None
    open_access: bool = False
    citation_count: int = 0
    source: str = "openalex"
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "doi": self.doi,
            "title": self.title,
            "openalex_id": self.openalex_id,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "abstract": self.abstract,
            "pdf_url": self.pdf_url,
            "open_access": self.open_access,
            "citation_count": self.citation_count,
            "source": self.source,
        }


class OpenAlexClient:
    """
    Client for the OpenAlex API.
    
    OpenAlex provides free access to scholarly metadata with generous rate limits
    when using the polite pool (by providing an email in the request).
    
    Rate Limits:
    - Without email: 10 requests/second (max)
    - With email (polite pool): 100,000 requests/day
    
    Features:
    - Email rotation for rate limit handling
    - Fulltext search across title, abstract, and keywords
    - Comprehensive error handling with retry
    """
    
    BASE_URL = "https://api.openalex.org"
    MAX_RETRIES = 3
    
    def __init__(
        self,
        email: Optional[str] = None,
        emails: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        requests_per_minute: int = 60,
        timeout: int = 30
    ):
        """
        Initialize OpenAlex client.
        
        Args:
            email: Single email for polite pool (legacy)
            emails: List of emails for rotation (preferred)
            api_key: API key for authenticated requests (recommended)
            requests_per_minute: Rate limit for requests
            timeout: Request timeout in seconds
        """
        # Support both single email and list
        if emails:
            self.emails = emails
        elif email:
            self.emails = [email]
        else:
            self.emails = []
        
        self.api_key = api_key
        self._current_email_idx = 0
        self.requests_per_minute = requests_per_minute
        self.timeout = timeout
        self._last_request_time = 0.0
        self._min_interval = 60.0 / requests_per_minute
        self._consecutive_errors = 0
        
        # Session for connection pooling
        self.session = requests.Session()
        self._update_user_agent()
    
    @property
    def email(self) -> Optional[str]:
        """Get current active email."""
        if self.emails:
            return self.emails[self._current_email_idx % len(self.emails)]
        return None
    
    def _update_user_agent(self):
        """Update User-Agent header with current email."""
        email = self.email
        if email:
            self.session.headers["User-Agent"] = f"SME-Research-Assistant/1.0 (mailto:{email})"
        else:
            self.session.headers["User-Agent"] = "SME-Research-Assistant/1.0"
    
    def _rotate_email(self):
        """Rotate to next email in list."""
        if len(self.emails) > 1:
            old_email = self.email
            self._current_email_idx = (self._current_email_idx + 1) % len(self.emails)
            self._update_user_agent()
            logger.info(f"Rotated email: {old_email} -> {self.email}")
    
    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()
    
    def _make_request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make a rate-limited request to the API with retry and email rotation."""
        last_error = None
        
        for attempt in range(self.MAX_RETRIES):
            self._rate_limit()
            
            # Add email to params if provided (for polite pool)
            current_email = self.email
            if current_email:
                params["mailto"] = current_email
            
            # Add API key if provided
            if self.api_key:
                params["api_key"] = self.api_key
            
            url = f"{self.BASE_URL}/{endpoint}"
            
            logger.info(f"OpenAlex Request: {url} Params: {params}") # DEBUG LOG

            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                
                # Handle rate limiting
                if response.status_code == 429:
                    logger.warning(f"Rate limited on email {current_email}, rotating...")
                    self._rotate_email()
                    wait_time = min(30 * (attempt + 1), 120)  # Exponential backoff capped at 2min
                    time.sleep(wait_time)
                    continue
                
                response.raise_for_status()
                self._consecutive_errors = 0
                return response.json()
                
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on attempt {attempt + 1}/{self.MAX_RETRIES}")
                last_error = "Timeout"
                time.sleep(5 * (attempt + 1))
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request failed on attempt {attempt + 1}: {e}")
                last_error = str(e)
                self._consecutive_errors += 1
                
                # Rotate email on consecutive failures
                if self._consecutive_errors >= 3:
                    self._rotate_email()
                    self._consecutive_errors = 0
                
                time.sleep(2 * (attempt + 1))
        
        logger.error(f"OpenAlex API request failed after {self.MAX_RETRIES} attempts: {last_error}")
        raise requests.exceptions.RequestException(f"Max retries exceeded: {last_error}")
    
    def search_papers(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        per_page: int = 100,
        max_results: int = 1000
    ) -> List[PaperMetadata]:
        """
        Search for papers matching the query.
        
        Args:
            query: Search query (keywords)
            filters: Optional filters (year, type, open_access)
            per_page: Results per page (max 200)
            max_results: Maximum total results to return
            
        Returns:
            List of PaperMetadata objects
        """
        return list(self.search_papers_generator(query, filters, per_page, max_results))

    def search_papers_generator(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        per_page: int = 100,
        max_results: int = 1000
    ):
        """
        Generator that yields papers matching the query page-by-page.
        
        Args:
            query: Search query (keywords)
            filters: Optional filters (year, type, open_access)
            per_page: Results per page (max 200)
            max_results: Maximum total results to return
            
        Yields:
            PaperMetadata objects
        """
        filters = filters or {}
        yielded_count = 0
        cursor = "*"
        
        # Build filter string
        filter_parts = []
        
        if filters.get("min_year"):
            filter_parts.append(f"publication_year:>{filters['min_year']-1}")
        
        if filters.get("max_year"):
            filter_parts.append(f"publication_year:<{filters['max_year']+1}")
        
        if filters.get("open_access_only"):
            filter_parts.append("is_oa:true")
        
        if filters.get("publication_types"):
            types = filters["publication_types"]
            if isinstance(types, list):
                types_str = "|".join(types)
                filter_parts.append(f"type:{types_str}")
        
        # Incremental discovery: from_updated_date filter
        if filters.get("from_updated_date"):
            filter_parts.append(f"from_updated_date:{filters['from_updated_date']}")
        
        # Always require a DOI
        filter_parts.append("has_doi:true")
        
        filter_string = ",".join(filter_parts) if filter_parts else None
        
        logger.info(f"Searching OpenAlex (stream) for: '{query}' with filters: {filter_string}")
        
        while yielded_count < max_results:
            params = {
                "search": query,
                "per-page": min(per_page, 200),
                "cursor": cursor,
                "select": "id,doi,title,authorships,publication_year,primary_location,abstract_inverted_index,open_access,cited_by_count"
            }
            
            if filter_string:
                params["filter"] = filter_string
            
            try:
                data = self._make_request("works", params)
            except Exception as e:
                logger.error(f"Failed to fetch results: {e}")
                break
            
            results = data.get("results", [])
            if not results:
                break
            
            for work in results:
                paper = self._parse_work(work)
                if paper and paper.doi:
                    yield paper
                    yielded_count += 1
                    if yielded_count >= max_results:
                        break
            
            # Get next cursor
            meta = data.get("meta", {})
            cursor = meta.get("next_cursor")
            if not cursor:
                break
            
            logger.debug(f"Yielded {yielded_count} papers so far...")
        
        logger.info(f"Found {yielded_count} papers for query: '{query}'")
    
    def _parse_work(self, work: Dict[str, Any]) -> Optional[PaperMetadata]:
        """Parse a work from OpenAlex into PaperMetadata."""
        try:
            # Extract DOI (clean format)
            doi_url = work.get("doi", "")
            doi = doi_url.replace("https://doi.org/", "") if doi_url else None
            
            if not doi:
                return None
            
            # Extract title
            title = work.get("title", "")
            if not title:
                return None
            
            # Extract authors
            authors = []
            for authorship in work.get("authorships", [])[:10]:  # Limit to 10 authors
                author_info = authorship.get("author", {})
                name = author_info.get("display_name")
                if name:
                    authors.append(name)
            
            # Extract year
            year = work.get("publication_year")
            
            # Extract venue
            venue = None
            primary_location = work.get("primary_location", {})
            if primary_location:
                source = primary_location.get("source", {})
                if source:
                    venue = source.get("display_name")
            
            # Extract abstract (from inverted index)
            abstract = None
            abstract_index = work.get("abstract_inverted_index")
            if abstract_index:
                abstract = self._reconstruct_abstract(abstract_index)
            
            # Extract PDF URL
            pdf_url = None
            oa_info = work.get("open_access", {})
            if oa_info.get("is_oa"):
                pdf_url = oa_info.get("oa_url")
            
            # Extract open access status
            is_oa = oa_info.get("is_oa", False) if oa_info else False
            
            # Citation count
            cited_by = work.get("cited_by_count", 0)
            
            # Extract OpenAlex ID from 'id' field (e.g., "https://openalex.org/W12345")
            openalex_url = work.get("id", "")
            openalex_id = openalex_url.split("/")[-1] if openalex_url else None
            
            return PaperMetadata(
                doi=doi,
                title=title,
                openalex_id=openalex_id,
                authors=authors,
                year=year,
                venue=venue,
                abstract=abstract,
                pdf_url=pdf_url,
                open_access=is_oa,
                citation_count=cited_by,
                source="openalex",
                raw_data=work
            )
            
        except Exception as e:
            logger.warning(f"Failed to parse work: {e}")
            return None
    
    def _reconstruct_abstract(self, inverted_index: Dict[str, List[int]]) -> str:
        """Reconstruct abstract from OpenAlex inverted index format."""
        if not inverted_index:
            return ""
        
        # Build word position mapping
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        
        # Sort by position and join
        word_positions.sort(key=lambda x: x[0])
        abstract = " ".join(word for _, word in word_positions)
        
        return abstract
    
    def get_paper_by_doi(self, doi: str) -> Optional[PaperMetadata]:
        """
        Get paper metadata by DOI.
        
        Args:
            doi: The paper's DOI
            
        Returns:
            PaperMetadata or None if not found
        """
        # Normalize DOI
        if doi.startswith("https://doi.org/"):
            doi = doi.replace("https://doi.org/", "")
        
        try:
            params = {
                "select": "id,doi,title,authorships,publication_year,primary_location,abstract_inverted_index,open_access,cited_by_count"
            }
            data = self._make_request(f"works/https://doi.org/{doi}", params)
            return self._parse_work(data)
        except Exception as e:
            logger.warning(f"Failed to get paper by DOI {doi}: {e}")
            return None
    
    def search_by_dois(self, dois: List[str], per_page: int = 100) -> List[PaperMetadata]:
        """
        Batch lookup papers by multiple DOIs in a single API request.
        
        Args:
            dois: List of DOIs to look up
            per_page: Results per page (max 200)
            
        Returns:
            List of PaperMetadata objects for found papers
        """
        if not dois:
            return []
        
        # Normalize DOIs
        normalized_dois = []
        for doi in dois:
            if doi.startswith("https://doi.org/"):
                doi = doi.replace("https://doi.org/", "")
            normalized_dois.append(doi)
        
        try:
            # OpenAlex filter format: doi:10.1234/abc|10.5678/xyz
            doi_filter = "|".join(normalized_dois)
            
            params = {
                "filter": f"doi:{doi_filter}",
                "per_page": min(per_page, 200),
                "select": "id,doi,title,authorships,publication_year,primary_location,abstract_inverted_index,open_access,cited_by_count"
            }
            
            data = self._make_request("works", params)
            
            if not data or "results" not in data:
                return []
            
            results = []
            for work in data.get("results", []):
                paper = self._parse_work(work)
                if paper:
                    results.append(paper)
            
            logger.info(f"Batch DOI lookup: {len(results)}/{len(dois)} found")
            return results
            
        except Exception as e:
            logger.warning(f"Batch DOI lookup failed: {e}")
            return []
    
    def close(self):
        """Close the HTTP session."""
        self.session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
