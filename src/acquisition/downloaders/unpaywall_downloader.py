"""
SME Research Assistant - Unpaywall API Downloader

Finds legal open access copies via Unpaywall API.
Free (100K calls/day with email), excellent for finding OA versions.
"""

import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any
import requests

logger = logging.getLogger(__name__)


class UnpaywallDownloader:
    """
    Find and download open access PDFs via Unpaywall API.
    
    Unpaywall finds legal OA copies across repositories, preprint servers,
    and institutional archives.
    """
    
    API_URL = "https://api.unpaywall.org/v2"
    
    def __init__(
        self,
        output_dir: Path,
        email: str,
        timeout: int = 60,
        max_retries: int = 3
    ):
        """
        Initialize Unpaywall downloader.
        
        Args:
            output_dir: Directory to save downloaded PDFs
            email: Email for Unpaywall API (required)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.email = email
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"SME-Research-Assistant/1.0 (mailto:{email})"
        })
    
    def normalize_doi(self, doi: str) -> str:
        """Normalize DOI to standard format."""
        doi = doi.strip()
        
        # Remove URL prefixes
        prefixes = [
            "https://doi.org/",
            "http://doi.org/",
            "https://dx.doi.org/",
            "http://dx.doi.org/",
            "doi:",
        ]
        for prefix in prefixes:
            if doi.lower().startswith(prefix.lower()):
                doi = doi[len(prefix):]
                break
        
        return doi.strip()
    
    def lookup(self, doi: str) -> Optional[Dict[str, Any]]:
        """
        Look up OA information for a DOI.
        
        Returns:
            Dict with OA info including best_oa_location, or None
        """
        doi = self.normalize_doi(doi)
        
        if not doi:
            return None
        
        url = f"{self.API_URL}/{doi}"
        params = {"email": self.email}
        
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                
                if response.status_code == 200:
                    return response.json()
                
                elif response.status_code == 404:
                    logger.debug(f"DOI not found in Unpaywall: {doi}")
                    return None
                
                elif response.status_code == 429:
                    wait_time = 2 ** attempt
                    logger.warning(f"Unpaywall rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                
                else:
                    logger.warning(f"Unpaywall lookup failed: {response.status_code}")
                    return None
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout looking up {doi}")
                time.sleep(2 ** attempt)
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error for {doi}: {e}")
                return None
        
        return None
    
    def get_pdf_url(self, doi: str) -> Optional[str]:
        """
        Get best available PDF URL for a DOI.
        
        Returns:
            PDF URL or None if not available
        """
        data = self.lookup(doi)
        
        if not data:
            return None
        
        # Check if OA
        if not data.get("is_oa"):
            logger.debug(f"Not open access: {doi}")
            return None
        
        # Get best OA location
        best_location = data.get("best_oa_location")
        if not best_location:
            # Try oa_locations
            locations = data.get("oa_locations", [])
            for loc in locations:
                if loc.get("url_for_pdf"):
                    return loc["url_for_pdf"]
            return None
        
        # Prefer url_for_pdf, fall back to url
        pdf_url = best_location.get("url_for_pdf")
        if pdf_url:
            return pdf_url
        
        # Some locations only have a landing page URL
        url = best_location.get("url")
        if url and url.endswith(".pdf"):
            return url
        
        return None
    
    def download(self, doi: str, filename: Optional[str] = None) -> Optional[Path]:
        """
        Find and download OA PDF for a DOI.
        
        Args:
            doi: DOI to look up
            filename: Optional custom filename
            
        Returns:
            Path to downloaded PDF, or None if failed
        """
        doi = self.normalize_doi(doi)
        
        if not doi:
            logger.warning("Empty DOI provided")
            return None
        
        # Get PDF URL from Unpaywall
        pdf_url = self.get_pdf_url(doi)
        
        if not pdf_url:
            logger.debug(f"No OA PDF found for {doi}")
            return None
        
        # Generate filename
        if filename is None:
            safe_doi = doi.replace("/", "_").replace(".", "_")
            filename = f"{safe_doi}.pdf"
        elif not filename.endswith(".pdf"):
            filename = f"{filename}.pdf"
        
        output_path = self.output_dir / filename
        
        # Skip if already exists
        if output_path.exists() and output_path.stat().st_size > 10240:
            logger.debug(f"Already exists: {output_path}")
            return output_path
        
        # Download PDF
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(
                    pdf_url,
                    timeout=self.timeout,
                    stream=True,
                    allow_redirects=True
                )
                
                if response.status_code == 200:
                    # Validate content type
                    content_type = response.headers.get("Content-Type", "")
                    if "pdf" not in content_type.lower() and "octet-stream" not in content_type.lower():
                        # Some servers don't set correct content-type, check magic bytes
                        pass
                    
                    # Write file
                    with open(output_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    # Validate PDF
                    if self._validate_pdf(output_path):
                        logger.info(f"Downloaded via Unpaywall: {doi}")
                        return output_path
                    else:
                        output_path.unlink(missing_ok=True)
                        logger.warning(f"Invalid PDF from Unpaywall for {doi}")
                        return None
                
                elif response.status_code in (403, 404):
                    logger.debug(f"PDF not accessible: {pdf_url}")
                    return None
                
                elif response.status_code == 429:
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
                    continue
                
                else:
                    logger.warning(f"Download failed: {response.status_code} from {pdf_url}")
                    return None
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout downloading from {pdf_url}")
                time.sleep(2 ** attempt)
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error: {e}")
                return None
        
        return None
    
    def _validate_pdf(self, path: Path) -> bool:
        """Validate that file is a valid PDF."""
        try:
            if path.stat().st_size < 1024:
                return False
            
            with open(path, "rb") as f:
                header = f.read(8)
                return header.startswith(b"%PDF-")
        except Exception:
            return False
    
    def close(self):
        """Close session."""
        self.session.close()
