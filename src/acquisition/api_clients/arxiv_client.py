"""
SME Research Assistant - arXiv API Client

arXiv is a free distribution service and open-access archive for scholarly articles.
https://info.arxiv.org/help/api/index.html

Features:
- Keyword-based paper search
- Direct PDF download URLs
- Preprint access (no paywalls)
"""

import logging
import time
import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
import requests

logger = logging.getLogger(__name__)

# arXiv API namespace
ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom"
}


@dataclass
class ArxivPaperMetadata:
    """Represents metadata for a paper from arXiv."""
    arxiv_id: str
    doi: Optional[str] = None
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    abstract: Optional[str] = None
    pdf_url: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    source: str = "arxiv"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "arxiv_id": self.arxiv_id,
            "doi": self.doi,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "abstract": self.abstract,
            "pdf_url": self.pdf_url,
            "categories": self.categories,
            "source": self.source,
        }


class ArxivClient:
    """
    Client for the arXiv API.
    
    arXiv provides free access to preprints with no API key required.
    All papers have direct PDF download links.
    
    Rate Limits:
    - Maximum 1 request per 3 seconds (recommended)
    - Be polite - this is a free service
    """
    
    BASE_URL = "http://export.arxiv.org/api/query"
    
    def __init__(
        self,
        requests_per_minute: int = 20,  # Conservative (1 per 3 sec)
        timeout: int = 30
    ):
        """
        Initialize arXiv client.
        
        Args:
            requests_per_minute: Rate limit for requests
            timeout: Request timeout in seconds
        """
        self.requests_per_minute = requests_per_minute
        self.timeout = timeout
        self._last_request_time = 0.0
        self._min_interval = 60.0 / requests_per_minute
        
        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "SME-Research-Assistant/1.0"
    
    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()
    
    def search_papers(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        max_results: int = 1000,
        sort_by: str = "relevance"
    ) -> List[ArxivPaperMetadata]:
        """
        Search for papers matching the query.
        
        Args:
            query: Search query (keywords)
            filters: Optional filters (categories, year)
            max_results: Maximum total results to return
            sort_by: Sort order (relevance, lastUpdatedDate, submittedDate)
            
        Returns:
            List of ArxivPaperMetadata objects
        """
        filters = filters or {}
        papers = []
        start = 0
        batch_size = 100  # Max 100 per request
        
        # Build search query
        search_query = self._build_query(query, filters)
        
        logger.info(f"Searching arXiv for: '{query}'")
        
        while len(papers) < max_results:
            self._rate_limit()
            
            params = {
                "search_query": search_query,
                "start": start,
                "max_results": min(batch_size, max_results - len(papers)),
                "sortBy": sort_by,
                "sortOrder": "descending"
            }
            
            try:
                response = self.session.get(
                    self.BASE_URL,
                    params=params,
                    timeout=self.timeout
                )
                response.raise_for_status()
                
                # Parse XML response
                batch_papers = self._parse_response(response.text)
                
                if not batch_papers:
                    break
                
                # Filter by year if specified
                min_year = filters.get("min_year")
                if min_year:
                    batch_papers = [p for p in batch_papers if p.year and p.year >= min_year]
                
                papers.extend(batch_papers)
                start += len(batch_papers)
                
                logger.debug(f"Fetched {len(papers)} papers so far...")
                
                # Check if we got fewer results than requested (end of results)
                if len(batch_papers) < batch_size:
                    break
                    
            except Exception as e:
                logger.error(f"Failed to fetch arXiv results: {e}")
                break
        
        logger.info(f"Found {len(papers)} papers from arXiv")
        return papers[:max_results]
    
    def _build_query(self, query: str, filters: Dict[str, Any]) -> str:
        """Build arXiv search query string."""
        # Basic search in title, abstract, and comments
        # We allow the user to provide quotes/logic in the config, passing the raw query string.
        # We wrap it in parentheses to ensure 'all:' applies to the entire complex query.
        parts = [f'all:({query})']
        
        # Add category filter if specified
        categories = filters.get("categories", [])
        if categories:
            cat_query = " OR ".join([f"cat:{cat}" for cat in categories])
            parts.append(f"({cat_query})")
            
        # Add date filter if specified (from_updated_date: YYYY-MM-DD)
        if filters.get("from_updated_date"):
            date_str = filters["from_updated_date"].replace("-", "") # YYYYMMDD
            # Start of day
            start_ts = f"{date_str}0000"
            # End of time (far future)
            end_ts = "999912312359"
            
            # Filter by submittedDate OR updatedDate
            # Syntax: submittedDate:[202401010000 TO 999912312359]
            date_query = (
                f"(submittedDate:[{start_ts} TO {end_ts}] OR "
                f"updatedDate:[{start_ts} TO {end_ts}])"
            )
            parts.append(date_query)
        
        return " AND ".join(parts)
    
    def _parse_response(self, xml_content: str) -> List[ArxivPaperMetadata]:
        """Parse arXiv API XML response."""
        papers = []
        
        try:
            root = ET.fromstring(xml_content)
            
            for entry in root.findall("atom:entry", ARXIV_NS):
                paper = self._parse_entry(entry)
                if paper:
                    papers.append(paper)
                    
        except ET.ParseError as e:
            logger.error(f"Failed to parse arXiv XML: {e}")
        
        return papers
    
    def _parse_entry(self, entry: ET.Element) -> Optional[ArxivPaperMetadata]:
        """Parse a single entry from arXiv response."""
        try:
            # Extract arXiv ID
            id_elem = entry.find("atom:id", ARXIV_NS)
            if id_elem is None or id_elem.text is None:
                return None
            
            # Parse arXiv ID from URL
            arxiv_id = id_elem.text.split("/abs/")[-1]
            # Remove version if present
            arxiv_id_base = re.sub(r"v\d+$", "", arxiv_id)
            
            # Extract title
            title_elem = entry.find("atom:title", ARXIV_NS)
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else None
            # Clean up whitespace
            if title:
                title = " ".join(title.split())
            
            # Extract authors
            authors = []
            for author_elem in entry.findall("atom:author", ARXIV_NS):
                name_elem = author_elem.find("atom:name", ARXIV_NS)
                if name_elem is not None and name_elem.text:
                    authors.append(name_elem.text)
            
            # Extract abstract
            abstract_elem = entry.find("atom:summary", ARXIV_NS)
            abstract = abstract_elem.text.strip() if abstract_elem is not None and abstract_elem.text else None
            if abstract:
                abstract = " ".join(abstract.split())
            
            # Extract published date -> year
            published_elem = entry.find("atom:published", ARXIV_NS)
            year = None
            if published_elem is not None and published_elem.text:
                year = int(published_elem.text[:4])
            
            # Extract DOI if available
            doi_elem = entry.find("arxiv:doi", ARXIV_NS)
            doi = doi_elem.text if doi_elem is not None else None
            
            # Extract categories
            categories = []
            for cat_elem in entry.findall("atom:category", ARXIV_NS):
                term = cat_elem.get("term")
                if term:
                    categories.append(term)
            
            # Build PDF URL
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id_base}.pdf"
            
            return ArxivPaperMetadata(
                arxiv_id=arxiv_id_base,
                doi=doi,
                title=title,
                authors=authors[:10],  # Limit authors
                year=year,
                abstract=abstract,
                pdf_url=pdf_url,
                categories=categories,
                source="arxiv"
            )
            
        except Exception as e:
            logger.warning(f"Failed to parse arXiv entry: {e}")
            return None
    
    def get_paper_by_id(self, arxiv_id: str) -> Optional[ArxivPaperMetadata]:
        """
        Get paper metadata by arXiv ID.
        
        Args:
            arxiv_id: The arXiv paper ID (e.g., "2301.12345")
            
        Returns:
            ArxivPaperMetadata or None if not found
        """
        self._rate_limit()
        
        # Normalize ID
        arxiv_id = arxiv_id.replace("arXiv:", "")
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
        
        params = {
            "id_list": arxiv_id,
            "max_results": 1
        }
        
        try:
            response = self.session.get(
                self.BASE_URL,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            papers = self._parse_response(response.text)
            return papers[0] if papers else None
            
        except Exception as e:
            logger.warning(f"Failed to get arXiv paper {arxiv_id}: {e}")
            return None
    
    def close(self):
        """Close the HTTP session."""
        self.session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
