"""
SME Research Assistant - Semantic Scholar API Client

Semantic Scholar provides AI-powered scholarly search and paper metadata.
https://www.semanticscholar.org/product/api

Features:
- Keyword-based paper search
- Paper details by ID or DOI
- Open access PDF links (when available)
- Citation and reference data
"""

import logging
import time
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
import requests

logger = logging.getLogger(__name__)


@dataclass
class S2PaperMetadata:
    """Represents metadata for a paper from Semantic Scholar."""
    paper_id: str
    doi: Optional[str] = None
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    pdf_url: Optional[str] = None
    open_access: bool = False
    citation_count: int = 0
    source: str = "semantic_scholar"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "paper_id": self.paper_id,
            "doi": self.doi,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "abstract": self.abstract,
            "pdf_url": self.pdf_url,
            "open_access": self.open_access,
            "citation_count": self.citation_count,
            "source": self.source,
        }


class SemanticScholarClient:
    """
    Client for the Semantic Scholar API.
    
    Provides access to scholarly paper metadata with optional API key
    for higher rate limits.
    
    Rate Limits (without key):
    - Graph API: 100 requests per 5 minutes
    - Search API: 1 request per second
    
    Rate Limits (with key):
    - Up to 100 requests per second (depending on tier)
    """
    
    BASE_URL = "https://api.semanticscholar.org"
    GRAPH_URL = f"{BASE_URL}/graph/v1"
    
    # Fields to request
    PAPER_FIELDS = [
        "paperId",
        "externalIds",
        "title",
        "authors",
        "year",
        "venue",
        "abstract",
        "openAccessPdf",
        "citationCount",
        "isOpenAccess"
    ]
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        requests_per_minute: int = 10,  # Conservative default
        timeout: int = 30
    ):
        """
        Initialize Semantic Scholar client.
        
        Args:
            api_key: Optional API key for higher rate limits
            requests_per_minute: Rate limit for requests
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.requests_per_minute = requests_per_minute
        self.timeout = timeout
        self._last_request_time = 0.0
        self._min_interval = 60.0 / requests_per_minute
        
        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "SME-Research-Assistant/1.0"
        
        if api_key:
            self.session.headers["x-api-key"] = api_key
    
    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()
    
    def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        method: str = "GET",
        max_retries: int = 5
    ) -> Dict[str, Any]:
        """Make a rate-limited request to the API with exponential backoff."""
        import random
        
        url = f"{self.GRAPH_URL}/{endpoint}"
        last_exception = None
        
        for attempt in range(max_retries):
            self._rate_limit()
            
            try:
                if method == "GET":
                    response = self.session.get(url, params=params, timeout=self.timeout)
                else:
                    response = self.session.post(url, params=params, json=json_data, timeout=self.timeout)
                
                # Check for rate limit (429)
                if response.status_code == 429:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        f"Rate limited (429). Attempt {attempt + 1}/{max_retries}. "
                        f"Waiting {wait_time:.1f}s..."
                    )
                    time.sleep(wait_time)
                    last_exception = requests.exceptions.HTTPError(response=response)
                    continue
                
                response.raise_for_status()
                return response.json()
                
            except requests.exceptions.HTTPError as e:
                if hasattr(e, 'response') and e.response is not None and e.response.status_code == 429:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"Rate limited (429). Waiting {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    last_exception = e
                    continue
                logger.error(f"Semantic Scholar API request failed: {e}")
                raise
            except requests.exceptions.RequestException as e:
                logger.error(f"Semantic Scholar API request failed: {e}")
                raise
        
        # Max retries exceeded
        logger.error(f"Max retries ({max_retries}) exceeded for {endpoint}")
        if last_exception:
            raise last_exception
        raise requests.exceptions.RequestException(f"Failed after {max_retries} retries")
    
    def search_papers(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        max_results: int = 1000
    ) -> List[S2PaperMetadata]:
        """
        Search for papers matching the query.
        
        Args:
            query: Search query (keywords)
            filters: Optional filters (year range, open_access)
            limit: Results per page (max 100)
            max_results: Maximum total results to return
            
        Returns:
            List of S2PaperMetadata objects
        """
        filters = filters or {}
        papers = []
        offset = 0
        
        # Build year filter
        year_filter = None
        min_year = filters.get("min_year", 1900)
        max_year = filters.get("max_year", 2100)
        
        # Incremental discovery fallback: map from_updated_date to min_year
        if filters.get("from_updated_date"):
            try:
                # Extract year from YYYY-MM-DD
                from_year = int(filters["from_updated_date"].split("-")[0])
                min_year = max(min_year, from_year)
            except (ValueError, IndexError):
                logger.warning(f"Invalid date format for filter: {filters['from_updated_date']}")

        if min_year > 1900 or max_year < 2100:
            year_filter = f"{min_year}-{max_year}"
        
        # Open access filter
        open_access_only = filters.get("open_access_only", False)
        
        logger.info(f"Searching Semantic Scholar for: '{query}'")
        
        while len(papers) < max_results:
            params = {
                "query": query,
                "limit": min(limit, 100),
                "offset": offset,
                "fields": ",".join(self.PAPER_FIELDS)
            }
            
            if year_filter:
                params["year"] = year_filter
            
            if open_access_only:
                params["openAccessPdf"] = ""  # Filter for papers with OA PDFs
            
            # Publication Types parameter
            if filters.get("publication_types"):
                types = filters["publication_types"]
                if types:
                    params["publicationTypes"] = ",".join(types)
            
            try:
                data = self._make_request("paper/search", params)
            except Exception as e:
                logger.error(f"Failed to fetch results: {e}")
                break
            
            results = data.get("data", [])
            if not results:
                break
            
            for paper_data in results:
                paper = self._parse_paper(paper_data)
                if paper:
                    papers.append(paper)
                    if len(papers) >= max_results:
                        break
            
            # Check if more results available
            total = data.get("total", 0)
            offset += len(results)
            
            if offset >= total:
                break
            
            logger.debug(f"Fetched {len(papers)} papers so far...")
        
        logger.info(f"Found {len(papers)} papers for query: '{query}'")
        return papers
    
    def _parse_paper(self, data: Dict[str, Any]) -> Optional[S2PaperMetadata]:
        """Parse paper data into S2PaperMetadata."""
        try:
            paper_id = data.get("paperId")
            if not paper_id:
                return None
            
            # Extract DOI
            external_ids = data.get("externalIds", {})
            doi = external_ids.get("DOI")
            
            # Extract title
            title = data.get("title")
            
            # Extract authors
            authors = []
            for author in data.get("authors", [])[:10]:
                name = author.get("name")
                if name:
                    authors.append(name)
            
            # Extract year
            year = data.get("year")
            
            # Extract venue
            venue = data.get("venue")
            
            # Extract abstract
            abstract = data.get("abstract")
            
            # Extract PDF URL
            pdf_url = None
            oa_pdf = data.get("openAccessPdf")
            if oa_pdf:
                pdf_url = oa_pdf.get("url")
            
            # Open access status
            is_oa = data.get("isOpenAccess", False)
            
            # Citation count
            citation_count = data.get("citationCount", 0)
            
            return S2PaperMetadata(
                paper_id=paper_id,
                doi=doi,
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                abstract=abstract,
                pdf_url=pdf_url,
                open_access=is_oa,
                citation_count=citation_count,
                source="semantic_scholar"
            )
            
        except Exception as e:
            logger.warning(f"Failed to parse paper: {e}")
            return None
    
    def get_paper_by_doi(self, doi: str) -> Optional[S2PaperMetadata]:
        """
        Get paper metadata by DOI.
        
        Args:
            doi: The paper's DOI
            
        Returns:
            S2PaperMetadata or None if not found
        """
        # Normalize DOI
        if doi.startswith("https://doi.org/"):
            doi = doi.replace("https://doi.org/", "")
        
        try:
            params = {"fields": ",".join(self.PAPER_FIELDS)}
            data = self._make_request(f"paper/DOI:{doi}", params)
            return self._parse_paper(data)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.debug(f"Paper not found: {doi}")
            else:
                logger.warning(f"Failed to get paper by DOI {doi}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Failed to get paper by DOI {doi}: {e}")
            return None
    
    def get_paper_by_id(self, paper_id: str) -> Optional[S2PaperMetadata]:
        """
        Get paper metadata by Semantic Scholar paper ID.
        
        Args:
            paper_id: The Semantic Scholar paper ID
            
        Returns:
            S2PaperMetadata or None if not found
        """
        try:
            params = {"fields": ",".join(self.PAPER_FIELDS)}
            data = self._make_request(f"paper/{paper_id}", params)
            return self._parse_paper(data)
        except Exception as e:
            logger.warning(f"Failed to get paper by ID {paper_id}: {e}")
            return None
    
    
    def get_papers_by_dois(self, dois: List[str]) -> List[S2PaperMetadata]:
        """
        Batch lookup papers by multiple DOIs.
        
        Args:
            dois: List of DOIs to look up
            
        Returns:
            List of S2PaperMetadata objects found
        """
        if not dois:
            return []
            
        # Normalize
        clean_dois = []
        for d in dois:
            if d.startswith("https://doi.org/"):
                d = d.replace("https://doi.org/", "")
            clean_dois.append(f"DOI:{d}")
            
        results = []
        
        # Batch into chunks of 500 (API limit)
        # Using smaller chunks (50) to be safe with URL length/timeouts
        chunk_size = 50
        
        for i in range(0, len(clean_dois), chunk_size):
            chunk = clean_dois[i:i + chunk_size]
            try:
                # Use POST /graph/v1/paper/batch
                # 'fields' must be a query parameter
                # 'ids' must be in the JSON body
                params = {
                    "fields": ",".join(self.PAPER_FIELDS)
                }
                
                json_data = {
                    "ids": chunk
                }
                
                data = self._make_request("paper/batch", params=params, json_data=json_data, method="POST")
                
                for item in data:
                    if item:  # Can be None if id not found
                        paper = self._parse_paper(item)
                        if paper:
                            results.append(paper)
                            
                # Rate limit sleep
                time.sleep(0.5)
                
            except Exception as e:
                logger.warning(f"Batch Semantic Scholar lookup failed for chunk: {e}")
                logger.info("Falling back to sequential lookup for this chunk...")
                
                # Fallback to sequential
                for doi_str in chunk:
                    # Strip DOI: prefix for single lookup method if present
                    single_doi = doi_str.replace("DOI:", "") if doi_str.startswith("DOI:") else doi_str
                    try:
                        paper = self.get_paper_by_doi(single_doi)
                        if paper:
                            results.append(paper)
                        time.sleep(0.1)  # Brief pause between sequential calls
                    except Exception as seq_e:
                        logger.debug(f"Sequential lookup failed for {single_doi}: {seq_e}")
                
        logger.info(f"Batch S2 lookup: {len(results)}/{len(dois)} found")
        return results

    def close(self):
        """Close the HTTP session."""
        self.session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

