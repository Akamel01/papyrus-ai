"""
SME Research Assistant - Paper Acquisition Module

Provides tools for discovering and downloading academic papers
from various sources like OpenAlex, Semantic Scholar, and arXiv.
"""

from .paper_discoverer import PaperDiscoverer
from .paper_downloader import PaperDownloader

__all__ = [
    "PaperDiscoverer",
    "PaperDownloader",
]
