"""
SME Research Assistant - Crossref API Client

Crossref provides authoritative DOI-based metadata for scholarly works.
https://api.crossref.org/

Features:
- "Polite" pool usage via email
- Strict rate limit handling
- Deep coverage of DOIs
"""

import logging
import time
import requests
from typing import List, Dict, Any, Optional
from .openalex import PaperMetadata  # Reuse data structure

logger = logging.getLogger(__name__)


class CrossrefClient:
    """
    Client for the Crossref REST API.
    
    API Docs: https://api.crossref.org/swagger-ui/index.html
    
    Rate Limits:
    - Polite pool (with email): Generous, but requires 'User-Agent' and 'mailto' header
    - Standard: Higher reliability if compliant
    """
    
    BASE_URL = "https://api.crossref.org"
    MAX_RETRIES = 3
    
    def __init__(
        self,
        email: Optional[str] = None,
        emails: Optional[List[str]] = None,
        requests_per_minute: int = 50,
        timeout: int = 30
    ):
        """
        Initialize Crossref client.
        
        Args:
            email: Email for polite pool
            emails: List of emails (only first is used for 'mailto' identity usually)
            requests_per_minute: Rate limit config
            timeout: Request timeout seconds
        """
        # Crossref prefers a persistent identity, so we just pick the first provided email
        self.email = email
        if emails and not self.email:
            self.email = emails[0]
            
        self.requests_per_minute = requests_per_minute
        self.timeout = timeout
        
        self.session = requests.Session()
        self._update_headers()
        
        # Rate limiting state
        self._last_request_time = 0.0
        self._min_interval = 60.0 / requests_per_minute

    def _update_headers(self):
        """Set polite pool headers."""
        if self.email:
            # Crossref specific header format: "MyBot/1.0 (mailto:email@example.com)"
            user_agent = f"SME-Research-Assistant/1.0 (mailto:{self.email})"
            self.session.headers.update({
                "User-Agent": user_agent,
                "Mailer": "SME-Research-Assistant/1.0"
            })
        else:
            self.session.headers["User-Agent"] = "SME-Research-Assistant/1.0"

    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def _make_request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make a request to Crossref API."""
        url = f"{self.BASE_URL}/{endpoint}"
        last_error = None
        
        for attempt in range(self.MAX_RETRIES):
            self._rate_limit()
            
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                
                # Handle Rate Limits (Code 429)
                if response.status_code == 429:
                    logger.warning(f"Crossref Rate Limited. Waiting...")
                    time.sleep(5 * (attempt + 1))
                    continue

                response.raise_for_status()
                return response.json()
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"Crossref Request failed (Attempt {attempt+1}): {e}")
                last_error = e
                time.sleep(2 * (attempt + 1))
        
        logger.error(f"Crossref failure after {self.MAX_RETRIES} attempts: {last_error}")
        raise requests.exceptions.RequestException(f"Crossref failed: {last_error}")

    def search_papers(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        max_results: int = 100
    ) -> List[PaperMetadata]:
        """
        Search for works in Crossref.
        
        Note: Crossref keyword search is separate from 'filter' param.
        """
        filters = filters or {}
        papers = []
        
        # Build Filter String
        # Crossref filters: https://api.crossref.org/swagger-ui/index.html
        filter_parts = []
        
        # Years
        if filters.get("min_year"):
            filter_parts.append(f"from-pub-date:{filters['min_year']}")
        if filters.get("max_year"):
            if isinstance(filters["max_year"], int):
                filter_parts.append(f"until-pub-date:{filters['max_year']}")
        
        # Type filtering (Dynamic)
        # Crossref uses 'type', e.g. 'journal-article'
        if filters.get("publication_types"):
             types = filters["publication_types"]
             # Create filter string: type:journal-article,type:proceedings-article
             type_parts = [f"type:{t}" for t in types]
             filter_parts.append(",".join(type_parts))
        
        filter_str = ",".join(filter_parts)
        
        rows = min(max_results, 100)
        params = {
            "query": query,
            "rows": rows,
            "filter": filter_str,
            "select": "DOI,title,author,created,abstract,is-referenced-by-count,container-title"
        }
        
        try:
            data = self._make_request("works", params)
            items = data.get("message", {}).get("items", [])
            
            for item in items:
                paper = self._parse_item(item)
                if paper:
                    papers.append(paper)
                    
        except Exception as e:
            logger.error(f"Search failed for '{query}': {e}")
            
        return papers

    def _parse_item(self, item: Dict[str, Any]) -> Optional[PaperMetadata]:
        """Convert Crossref item to PaperMetadata."""
        try:
            doi = item.get("DOI")
            if not doi:
                return None
                
            # Title
            title_list = item.get("title", [])
            title = title_list[0] if title_list else "Unknown Title"
            
            # Authors
            authors = []
            for a in item.get("author", []):
                given = a.get("given", "")
                family = a.get("family", "")
                if family:
                    authors.append(f"{given} {family}".strip())
            
            # Year
            # 'created' or 'published-print' or 'published-online'
            date_parts = item.get("created", {}).get("date-parts", [[]])[0]
            year = date_parts[0] if date_parts else None
            
            # Venue
            container_title = item.get("container-title", [])
            venue = container_title[0] if container_title else None
            
            # Abstract (often missing in Crossref, sometimes XML)
            abstract = item.get("abstract")
            # Minimal cleaning if abstract exists
            if abstract and "<" in abstract:
                 # Very basic tag stripping, better handled by proper parser if needed
                 # For now, we trust downstream cleanup or keep raw XML-ish
                 pass
            
            # Citation Count
            cited_by = item.get("is-referenced-by-count", 0)
            
            return PaperMetadata(
                doi=doi.lower(),  # Normalized
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                abstract=abstract,
                citation_count=cited_by,
                source="crossref",
                open_access=False, # Crossref doesn't reliably signal OA URL in standard fields
                pdf_url=None,      # Crossref rarely has direct PDF links
                raw_data=item
            )
            
        except Exception as e:
            logger.warning(f"Error parsing Crossref item: {e}")
            return None

    def close(self):
        self.session.close()
