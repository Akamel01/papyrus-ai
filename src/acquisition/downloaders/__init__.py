"""
SME Research Assistant - Downloaders Package

Multi-source paper download with cascading fallback.
"""

from .arxiv_downloader import ArxivDownloader
from .openalex_content import OpenAlexContentDownloader
from .unpaywall_downloader import UnpaywallDownloader

__all__ = [
    "ArxivDownloader",
    "OpenAlexContentDownloader",
    "UnpaywallDownloader",
]
