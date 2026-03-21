"""
SME Research Assistant - OpenAlex Content API Downloader

Downloads PDFs via OpenAlex Content API.
Requires API key, costs 100 credits per download.
"""

import logging
import time
from pathlib import Path
from typing import Optional
import requests

logger = logging.getLogger(__name__)


class OpenAlexContentDownloader:
    """
    Download PDFs via OpenAlex Content API.
    
    URL pattern: https://content.openalex.org/works/{openalex_id}.pdf
    Requires API key for authentication.
    """
    
    BASE_URL = "https://content.openalex.org/works"
    
    def __init__(
        self,
        output_dir: Path,
        api_key: str,
        timeout: int = 60,
        max_retries: int = 3
    ):
        """
        Initialize OpenAlex Content downloader.
        
        Args:
            output_dir: Directory to save downloaded PDFs
            api_key: OpenAlex API key
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "SME-Research-Assistant/1.0",
            "Authorization": f"Bearer {api_key}"
        })
    
    def extract_openalex_id(self, identifier: str) -> Optional[str]:
        """
        Extract OpenAlex ID from various formats.
        
        Handles:
        - Full URL: https://openalex.org/W12345 -> W12345
        - ID only: W12345 -> W12345
        - Without prefix: 12345 -> W12345
        """
        if not identifier:
            return None
        
        identifier = identifier.strip()
        
        # Extract from URL
        if "openalex.org" in identifier:
            parts = identifier.rstrip("/").split("/")
            identifier = parts[-1]
        
        # Ensure W prefix
        if identifier.isdigit():
            identifier = f"W{identifier}"
        
        # Validate format
        if identifier.startswith("W") and identifier[1:].isdigit():
            return identifier
        
        return None
    
    def download(
        self,
        openalex_id: str,
        doi: Optional[str] = None,
        filename: Optional[str] = None
    ) -> Optional[Path]:
        """
        Download PDF from OpenAlex Content API.
        
        Args:
            openalex_id: OpenAlex work ID (e.g., "W12345")
            doi: Optional DOI for filename
            filename: Optional custom filename
            
        Returns:
            Path to downloaded PDF, or None if failed
        """
        openalex_id = self.extract_openalex_id(openalex_id)
        
        if not openalex_id:
            logger.warning("Invalid OpenAlex ID provided")
            return None
        
        # Construct URL
        url = f"{self.BASE_URL}/{openalex_id}.pdf"
        
        # Generate filename
        if filename is None:
            if doi:
                safe_doi = doi.replace("/", "_").replace(".", "_")
                filename = f"{safe_doi}.pdf"
            else:
                filename = f"{openalex_id}.pdf"
        elif not filename.endswith(".pdf"):
            filename = f"{filename}.pdf"
        
        output_path = self.output_dir / filename
        
        # Skip if already exists
        if output_path.exists() and output_path.stat().st_size > 10240:
            logger.debug(f"Already exists: {output_path}")
            return output_path
        
        # Download with retry
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, timeout=self.timeout, stream=True)
                
                if response.status_code == 200:
                    # Validate content type
                    content_type = response.headers.get("Content-Type", "")
                    if "pdf" not in content_type.lower() and "octet-stream" not in content_type.lower():
                        logger.warning(f"Not a PDF: {content_type} for {openalex_id}")
                        return None
                    
                    # Write file
                    start_time = time.time()
                    with open(output_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if time.time() - start_time > self.timeout:
                                raise requests.exceptions.Timeout(f"Download exceeded {self.timeout}s limit")
                            f.write(chunk)
                    
                    # Validate PDF
                    if self._validate_pdf(output_path):
                        logger.info(f"Downloaded via OpenAlex Content: {openalex_id}")
                        return output_path
                    else:
                        output_path.unlink(missing_ok=True)
                        logger.warning(f"Invalid PDF content for {openalex_id}")
                        return None
                
                elif response.status_code == 404:
                    logger.debug(f"No content available for {openalex_id}")
                    return None
                
                elif response.status_code == 402:
                    logger.warning("OpenAlex credits exhausted")
                    return None
                
                elif response.status_code == 429:
                    wait_time = 2 ** attempt
                    logger.warning(f"OpenAlex rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                
                else:
                    logger.warning(f"OpenAlex download failed: {response.status_code}")
                    return None
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout for {openalex_id}, attempt {attempt + 1}/{self.max_retries}")
                time.sleep(2 ** attempt)
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error for {openalex_id}: {e}")
                return None
        
        logger.error(f"Failed to download {openalex_id} after {self.max_retries} attempts")
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
