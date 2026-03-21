"""
SME Research Assistant - arXiv Paper Downloader

Direct download from arXiv.org for preprint papers.
100% reliable for valid arXiv IDs, no API key required.
"""

import logging
import re
import time
from pathlib import Path
from typing import Optional
import requests

logger = logging.getLogger(__name__)


class ArxivDownloader:
    """
    Download PDFs directly from arXiv.
    
    Supports both arxiv ID formats:
    - New format: 2301.12345
    - Old format: cs.AI/0301001
    """
    
    BASE_URL = "https://arxiv.org/pdf"
    
    def __init__(
        self,
        output_dir: Path,
        timeout: int = 60,
        max_retries: int = 3
    ):
        """
        Initialize arXiv downloader.
        
        Args:
            output_dir: Directory to save downloaded PDFs
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "SME-Research-Assistant/1.0 (mailto:ahmedbayoumi@cu.edu.eg)"
        })
    
    def normalize_arxiv_id(self, arxiv_id: str) -> str:
        """
        Normalize arXiv ID to standard format.
        
        Handles:
        - Full URLs: https://arxiv.org/abs/2301.12345 -> 2301.12345
        - With version: 2301.12345v2 -> 2301.12345v2
        - Old format: cs.AI/0301001 -> cs.AI/0301001
        """
        # Remove URL prefix
        if "arxiv.org" in arxiv_id:
            match = re.search(r'(?:abs|pdf)/(.+?)(?:\.pdf)?$', arxiv_id)
            if match:
                arxiv_id = match.group(1)
        
        # Clean up
        arxiv_id = arxiv_id.strip().rstrip('.pdf')
        
        return arxiv_id
    
    def download(self, arxiv_id: str, filename: Optional[str] = None) -> Optional[Path]:
        """
        Download PDF from arXiv.
        
        Args:
            arxiv_id: arXiv ID (e.g., "2301.12345" or "cs.AI/0301001")
            filename: Optional custom filename (without extension)
            
        Returns:
            Path to downloaded PDF, or None if failed
        """
        arxiv_id = self.normalize_arxiv_id(arxiv_id)
        
        if not arxiv_id:
            logger.warning("Empty arXiv ID provided")
            return None
        
        # Construct URL
        url = f"{self.BASE_URL}/{arxiv_id}.pdf"
        
        # Generate filename
        if filename is None:
            safe_id = arxiv_id.replace("/", "_").replace(".", "_")
            filename = f"arxiv_{safe_id}.pdf"
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
                        logger.warning(f"Not a PDF: {content_type} for {arxiv_id}")
                        return None
                    
                    # Write file
                    start_time = time.time()
                    with open(output_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if time.time() - start_time > self.timeout:
                                raise requests.exceptions.Timeout(f"Download exceeded {self.timeout}s limit")
                            if chunk:
                                f.write(chunk)
                    
                    # Validate PDF
                    if self._validate_pdf(output_path):
                        logger.info(f"Downloaded arXiv paper: {arxiv_id}")
                        return output_path
                    else:
                        output_path.unlink(missing_ok=True)
                        logger.warning(f"Invalid PDF content for {arxiv_id}")
                        return None
                
                elif response.status_code == 404:
                    logger.warning(f"arXiv paper not found: {arxiv_id}")
                    return None
                
                elif response.status_code == 503:
                    # Rate limited or overloaded
                    wait_time = 2 ** attempt
                    logger.warning(f"arXiv rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                
                else:
                    logger.warning(f"arXiv download failed: {response.status_code} for {arxiv_id}")
                    return None
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout downloading {arxiv_id}, attempt {attempt + 1}/{self.max_retries}")
                time.sleep(2 ** attempt)
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error for {arxiv_id}: {e}")
                return None
        
        logger.error(f"Failed to download {arxiv_id} after {self.max_retries} attempts")
        return None
    
    def _validate_pdf(self, path: Path) -> bool:
        """Validate that file is a valid PDF."""
        try:
            if path.stat().st_size < 1024:  # Less than 1KB
                return False
            
            with open(path, "rb") as f:
                header = f.read(8)
                return header.startswith(b"%PDF-")
        except Exception:
            return False
    
    def close(self):
        """Close session."""
        self.session.close()
