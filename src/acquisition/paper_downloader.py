"""
SME Research Assistant - Paper Downloader

Downloads PDF papers with retry logic, fallback sources, and proper error handling.

Features:
- PDF download with retry and exponential backoff
- Multi-source cascading fallback (arXiv, OpenAlex, Unpaywall)
- Rate limiting
- PDF validation
"""

import logging
import time
import re
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import requests
from urllib.parse import urlparse

from .api_clients.unpaywall import UnpaywallClient
from .paper_discoverer import DiscoveredPaper
from .downloaders.arxiv_downloader import ArxivDownloader
from .downloaders.openalex_content import OpenAlexContentDownloader
from .downloaders.unpaywall_downloader import UnpaywallDownloader

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    """Result of a download attempt."""
    success: bool
    paper: DiscoveredPaper
    file_path: Optional[Path] = None
    error: Optional[str] = None
    source_url: Optional[str] = None
    attempts: int = 0


@dataclass
class DownloadStats:
    """Statistics for download session."""
    total: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "successful": self.successful,
            "failed": self.failed,
            "skipped": self.skipped,
            "duration_seconds": (self.end_time - self.start_time).total_seconds() if self.start_time and self.end_time else 0
        }


class PaperDownloader:
    """
    Downloads PDF papers from various sources with robust error handling.
    
    Supports:
    - Direct PDF URLs from discovery
    - Unpaywall fallback for DOI resolution
    - Retry with exponential backoff
    - Rate limiting
    """
    
    def __init__(
        self,
        output_dir: Path,
        email: Optional[str] = None,
        openalex_api_key: Optional[str] = None,
        max_retries: int = 3,
        timeout: int = 120,
        requests_per_minute: int = 30,
        max_file_size_mb: int = 100,
        enable_cascade: bool = True
    ):
        """
        Initialize paper downloader.
        
        Args:
            output_dir: Directory to save downloaded PDFs
            email: Email for Unpaywall API
            openalex_api_key: API key for OpenAlex Content API
            max_retries: Maximum download attempts per paper
            timeout: Download timeout in seconds
            requests_per_minute: Rate limit for downloads
            max_file_size_mb: Maximum file size to download
            enable_cascade: Enable multi-source cascade fallback
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_retries = max_retries
        self.timeout = timeout
        self.max_file_size = max_file_size_mb * 1024 * 1024
        self._min_interval = 60.0 / requests_per_minute
        self._last_request_time = 0.0
        self.enable_cascade = enable_cascade
        
        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # Unpaywall client for PDF URL resolution
        self.unpaywall = None
        if email:
            self.unpaywall = UnpaywallClient(email=email)
        
        # Multi-source downloaders for cascade fallback
        self.arxiv_downloader = ArxivDownloader(
            output_dir=self.output_dir,
            timeout=timeout,
            max_retries=max_retries
        )
        
        self.openalex_downloader = None
        if openalex_api_key:
            self.openalex_downloader = OpenAlexContentDownloader(
                output_dir=self.output_dir,
                api_key=openalex_api_key,
                timeout=timeout,
                max_retries=max_retries
            )
        
        self.unpaywall_downloader = None
        if email:
            self.unpaywall_downloader = UnpaywallDownloader(
                output_dir=self.output_dir,
                email=email,
                timeout=timeout,
                max_retries=max_retries
            )
        
        # Track failed downloads for retry
        self._failed_downloads: List[Dict[str, Any]] = []
    
    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()
    
    def download_with_cascade(
        self,
        paper: DiscoveredPaper,
        filename: Optional[str] = None
    ) -> DownloadResult:
        """
        Download paper using cascading fallback strategy.
        
        Tries sources in order of reliability:
        1. arXiv (if arxiv_id available)
        2. OpenAlex Content API (if openalex_id available)
        3. Unpaywall (if DOI available)
        4. Direct URL (if pdf_url available)
        
        Args:
            paper: Paper to download
            filename: Optional custom filename
            
        Returns:
            DownloadResult with success/failure info
        """
        if not self.enable_cascade:
            # Fall back to original behavior
            file_path = self.output_dir / self._generate_filename(paper)
            return self._download_paper(paper, file_path)
        
        # Generate filename
        if filename is None:
            filename = self._generate_filename(paper)
        
        sources_tried = []
        
        # 1. Try arXiv (highest reliability for preprints)
        if paper.arxiv_id:
            sources_tried.append("arxiv")
            result = self.arxiv_downloader.download(paper.arxiv_id, filename)
            if result:
                logger.info(f"✓ Downloaded via arXiv: {paper.doi or paper.arxiv_id}")
                return DownloadResult(
                    success=True,
                    paper=paper,
                    file_path=result,
                    source_url=f"https://arxiv.org/pdf/{paper.arxiv_id}.pdf",
                    attempts=1
                )
        
        # 2. Try OpenAlex Content API
        if self.openalex_downloader and getattr(paper, 'openalex_id', None):
            sources_tried.append("openalex")
            result = self.openalex_downloader.download(
                paper.openalex_id, 
                doi=paper.doi, 
                filename=filename
            )
            if result:
                logger.info(f"✓ Downloaded via OpenAlex: {paper.doi}")
                return DownloadResult(
                    success=True,
                    paper=paper,
                    file_path=result,
                    source_url=f"https://content.openalex.org/works/{paper.openalex_id}.pdf",
                    attempts=len(sources_tried)
                )
        
        # 3. Try Unpaywall
        if self.unpaywall_downloader and paper.doi:
            sources_tried.append("unpaywall")
            result = self.unpaywall_downloader.download(paper.doi, filename=filename)
            if result:
                logger.info(f"✓ Downloaded via Unpaywall: {paper.doi}")
                return DownloadResult(
                    success=True,
                    paper=paper,
                    file_path=result,
                    source_url="unpaywall",
                    attempts=len(sources_tried)
                )
        
        # 4. Try direct URL (fallback)
        if paper.pdf_url:
            sources_tried.append("direct")
            self._rate_limit()
            file_path = self.output_dir / filename
            try:
                success = self._download_file(paper.pdf_url, file_path)
                if success:
                    logger.info(f"✓ Downloaded via direct URL: {paper.doi}")
                    return DownloadResult(
                        success=True,
                        paper=paper,
                        file_path=file_path,
                        source_url=paper.pdf_url,
                        attempts=len(sources_tried)
                    )
            except Exception as e:
                logger.debug(f"Direct download failed: {e}")
        
        # All sources failed
        error_msg = f"All sources failed ({', '.join(sources_tried)})"
        logger.warning(f"✗ {error_msg} for {paper.doi or paper.arxiv_id}")
        return DownloadResult(
            success=False,
            paper=paper,
            error=error_msg,
            attempts=len(sources_tried)
        )
    
    def download_papers(
        self,
        papers: List[DiscoveredPaper],
        skip_existing: bool = True,
        progress_callback: Optional[callable] = None
    ) -> tuple[List[DownloadResult], DownloadStats]:
        """
        Download a list of papers.
        
        Args:
            papers: List of papers to download
            skip_existing: Skip papers already downloaded
            progress_callback: Optional callback function(stats)
            
        Returns:
            Tuple of (results list, statistics)
        """
        stats = DownloadStats(total=len(papers))
        stats.start_time = datetime.now()
        results = []
        
        logger.info(f"Starting download of {len(papers)} papers...")
        
        for i, paper in enumerate(papers):
            # Generate filename
            filename = self._generate_filename(paper)
            file_path = self.output_dir / filename
            
            # Skip if already exists
            if skip_existing and file_path.exists():
                logger.debug(f"Skipping existing: {filename}")
                stats.skipped += 1
                results.append(DownloadResult(
                    success=True,
                    paper=paper,
                    file_path=file_path,
                    source_url="existing"
                ))
            else:
                # Download with cascade fallback
                result = self.download_with_cascade(paper, filename)
                results.append(result)
                
                if result.success:
                    stats.successful += 1
                    logger.info(f"[{i+1}/{len(papers)}] Downloaded: {filename}")
                else:
                    stats.failed += 1
                    self._failed_downloads.append({
                        "paper": paper.to_dict(),
                        "error": result.error,
                        "timestamp": datetime.now().isoformat()
                    })
                    logger.warning(f"[{i+1}/{len(papers)}] Failed: {filename} - {result.error}")
            
            # Send progress update via callback
            if progress_callback:
                try:
                    progress_callback(stats, paper, result)
                except Exception as e:
                    logger.error(f"Progress callback failed: {e}")

            # Progress logging every 10 papers
            if (i + 1) % 10 == 0:
                logger.info(
                    f"Progress: {i+1}/{len(papers)} "
                    f"(Success: {stats.successful}, Failed: {stats.failed}, Skipped: {stats.skipped})"
                )
        
        stats.end_time = datetime.now()
        
        logger.info(
            f"Download complete: {stats.successful} successful, "
            f"{stats.failed} failed, {stats.skipped} skipped"
        )
        
        return results, stats
    
    def _download_paper(
        self,
        paper: DiscoveredPaper,
        file_path: Path
    ) -> DownloadResult:
        """Download a single paper with retry logic."""
        pdf_urls = self._get_pdf_urls(paper)
        
        if not pdf_urls:
            return DownloadResult(
                success=False,
                paper=paper,
                error="No PDF URL available"
            )
        
        last_error = None
        total_attempts = 0
        
        for pdf_url in pdf_urls:
            for attempt in range(self.max_retries):
                total_attempts += 1
                
                try:
                    self._rate_limit()
                    success = self._download_file(pdf_url, file_path)
                    
                    if success:
                        return DownloadResult(
                            success=True,
                            paper=paper,
                            file_path=file_path,
                            source_url=pdf_url,
                            attempts=total_attempts
                        )
                        
                except Exception as e:
                    last_error = str(e)
                    logger.debug(f"Attempt {attempt + 1} failed for {pdf_url}: {e}")
                    
                    # Exponential backoff
                    if attempt < self.max_retries - 1:
                        wait_time = 2 ** attempt
                        time.sleep(wait_time)
        
        return DownloadResult(
            success=False,
            paper=paper,
            error=last_error or "All download attempts failed",
            attempts=total_attempts
        )
    
    def _get_pdf_urls(self, paper: DiscoveredPaper) -> List[str]:
        """Get list of PDF URLs to try for a paper."""
        urls = []
        
        # Primary URL from discovery
        if paper.pdf_url:
            urls.append(paper.pdf_url)
        
        # Try Unpaywall if we have a DOI
        if self.unpaywall and paper.doi:
            try:
                unpaywall_url = self.unpaywall.get_pdf_url(paper.doi)
                if unpaywall_url and unpaywall_url not in urls:
                    urls.append(unpaywall_url)
            except Exception as e:
                logger.debug(f"Unpaywall lookup failed: {e}")
        
        # arXiv direct URL
        if paper.arxiv_id:
            arxiv_url = f"https://arxiv.org/pdf/{paper.arxiv_id}.pdf"
            if arxiv_url not in urls:
                urls.append(arxiv_url)
        
        return urls
    
    def _download_file(self, url: str, file_path: Path) -> bool:
        """Download a file from URL."""
        try:
            # Head request to check file size
            head_response = self.session.head(url, timeout=10, allow_redirects=True)
            
            content_length = head_response.headers.get('Content-Length')
            if content_length and int(content_length) > self.max_file_size:
                raise ValueError(f"File too large: {int(content_length) / 1024 / 1024:.1f}MB")
            
            # Download file
            response = self.session.get(
                url,
                timeout=self.timeout,
                stream=True,
                allow_redirects=True
            )
            response.raise_for_status()
            
            # Verify it's a PDF
            content_type = response.headers.get('Content-Type', '')
            if 'application/pdf' not in content_type.lower():
                # Check if content starts with PDF magic bytes
                first_bytes = response.content[:8]
                if not first_bytes.startswith(b'%PDF'):
                    raise ValueError(f"Not a PDF: {content_type}")
            
            # Save file
            file_path.parent.mkdir(parents=True, exist_ok=True)
            start_time = time.time()
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if time.time() - start_time > self.timeout:
                        raise requests.exceptions.Timeout(f"Download exceeded {self.timeout}s limit")
                    f.write(chunk)
            
            # Verify file was written and is valid
            if not file_path.exists():
                raise ValueError("File was not saved")
            
            if file_path.stat().st_size < 1000:
                file_path.unlink()  # Delete invalid file
                raise ValueError("Downloaded file is too small (likely error page)")
            
            return True
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Download failed: {e}")
    
    def _generate_filename(self, paper: DiscoveredPaper) -> str:
        """Generate filename for paper based on DOI or arXiv ID."""
        if paper.doi:
            # Convert DOI to safe filename
            filename = paper.doi.replace("/", "_").replace(":", "_")
            filename = re.sub(r'[<>:"|?*]', '_', filename)
            return f"{filename}.pdf"
        
        if paper.arxiv_id:
            return f"arXiv-{paper.arxiv_id}.pdf"
        
        # Fallback to title hash
        import hashlib
        title_hash = hashlib.md5(paper.title.encode()).hexdigest()[:12]
        return f"paper-{title_hash}.pdf"
    
    def save_failed_downloads(self, path: Path):
        """Save failed downloads to a JSONL file for later retry."""
        with open(path, 'a', encoding='utf-8') as f:
            for failed in self._failed_downloads:
                f.write(json.dumps(failed) + '\n')
        
        logger.info(f"Saved {len(self._failed_downloads)} failed downloads to {path}")
        self._failed_downloads = []
    
    def close(self):
        """Close HTTP sessions."""
        self.session.close()
        if self.unpaywall:
            self.unpaywall.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
