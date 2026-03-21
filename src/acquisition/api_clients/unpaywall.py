"""
SME Research Assistant - Unpaywall API Client

Unpaywall finds legal, open access versions of academic papers.
https://unpaywall.org/products/api

Features:
- DOI-to-PDF URL resolution
- Returns best available open access location
- High reliability for finding free PDFs
"""

import logging
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass
import requests

logger = logging.getLogger(__name__)


@dataclass
class OpenAccessLocation:
    """Represents an open access location for a paper."""
    pdf_url: Optional[str] = None
    landing_page_url: Optional[str] = None
    host_type: Optional[str] = None  # publisher, repository
    version: Optional[str] = None  # publishedVersion, acceptedVersion, submittedVersion
    license: Optional[str] = None
    is_best: bool = False


class UnpaywallClient:
    """
    Client for the Unpaywall API.
    
    Unpaywall provides free access to open access paper locations.
    Requires an email address for API access.
    
    Rate Limits:
    - With email: 100,000 requests/day
    - Recommended: ~10 requests/second max
    """
    
    BASE_URL = "https://api.unpaywall.org/v2"
    
    def __init__(
        self,
        email: str,
        requests_per_minute: int = 60,
        timeout: int = 30
    ):
        """
        Initialize Unpaywall client.
        
        Args:
            email: Email for API access (required)
            requests_per_minute: Rate limit for requests
            timeout: Request timeout in seconds
        """
        if not email:
            raise ValueError("Email is required for Unpaywall API")
        
        self.email = email
        self.requests_per_minute = requests_per_minute
        self.timeout = timeout
        self._last_request_time = 0.0
        self._min_interval = 60.0 / requests_per_minute
        
        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers["User-Agent"] = f"SME-Research-Assistant/1.0 (mailto:{email})"
    
    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()
    
    def get_pdf_url(self, doi: str) -> Optional[str]:
        """
        Get the best open access PDF URL for a DOI.
        
        Args:
            doi: The paper's DOI
            
        Returns:
            PDF URL or None if not found
        """
        location = self.get_open_access_location(doi)
        if location:
            return location.pdf_url
        return None
    
    def get_open_access_location(self, doi: str) -> Optional[OpenAccessLocation]:
        """
        Get open access location details for a DOI.
        
        Args:
            doi: The paper's DOI
            
        Returns:
            OpenAccessLocation or None if not found
        """
        self._rate_limit()
        
        # Normalize DOI
        if doi.startswith("https://doi.org/"):
            doi = doi.replace("https://doi.org/", "")
        
        url = f"{self.BASE_URL}/{doi}"
        params = {"email": self.email}
        
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            
            if response.status_code == 404:
                logger.debug(f"DOI not found in Unpaywall: {doi}")
                return None
            
            response.raise_for_status()
            data = response.json()
            
            return self._parse_response(data)
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Unpaywall API request failed for {doi}: {e}")
            return None
    
    def _parse_response(self, data: Dict[str, Any]) -> Optional[OpenAccessLocation]:
        """Parse Unpaywall API response into OpenAccessLocation."""
        if not data.get("is_oa"):
            logger.debug(f"Paper is not open access: {data.get('doi')}")
            return None
        
        # Get best OA location
        best_location = data.get("best_oa_location")
        if not best_location:
            # Try oa_locations list
            oa_locations = data.get("oa_locations", [])
            if oa_locations:
                # Prefer PDF locations
                for loc in oa_locations:
                    if loc.get("url_for_pdf"):
                        best_location = loc
                        break
                if not best_location:
                    best_location = oa_locations[0]
        
        if not best_location:
            return None
        
        return OpenAccessLocation(
            pdf_url=best_location.get("url_for_pdf"),
            landing_page_url=best_location.get("url_for_landing_page"),
            host_type=best_location.get("host_type"),
            version=best_location.get("version"),
            license=best_location.get("license"),
            is_best=True
        )
    
    def get_all_locations(self, doi: str) -> list[OpenAccessLocation]:
        """
        Get all open access locations for a DOI.
        
        Args:
            doi: The paper's DOI
            
        Returns:
            List of OpenAccessLocation objects
        """
        self._rate_limit()
        
        # Normalize DOI
        if doi.startswith("https://doi.org/"):
            doi = doi.replace("https://doi.org/", "")
        
        url = f"{self.BASE_URL}/{doi}"
        params = {"email": self.email}
        
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            
            if response.status_code == 404:
                return []
            
            response.raise_for_status()
            data = response.json()
            
            locations = []
            best_url = None
            best_loc = data.get("best_oa_location", {})
            if best_loc:
                best_url = best_loc.get("url_for_pdf")
            
            for loc_data in data.get("oa_locations", []):
                loc = OpenAccessLocation(
                    pdf_url=loc_data.get("url_for_pdf"),
                    landing_page_url=loc_data.get("url_for_landing_page"),
                    host_type=loc_data.get("host_type"),
                    version=loc_data.get("version"),
                    license=loc_data.get("license"),
                    is_best=(loc_data.get("url_for_pdf") == best_url)
                )
                locations.append(loc)
            
            return locations
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Unpaywall API request failed for {doi}: {e}")
            return []
    
    def close(self):
        """Close the HTTP session."""
        self.session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
