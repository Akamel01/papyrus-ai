"""
SME Research Assistant - API Clients for Paper Acquisition

Provides clients for interacting with academic paper APIs:
- OpenAlex: Comprehensive open scholarly metadata
- Unpaywall: Legal open access PDF URLs
- Semantic Scholar: AI-powered paper discovery
- arXiv: Preprint repository
"""

from .openalex import OpenAlexClient
from .unpaywall import UnpaywallClient
from .semantic_scholar import SemanticScholarClient
from .arxiv_client import ArxivClient

__all__ = [
    "OpenAlexClient",
    "UnpaywallClient",
    "SemanticScholarClient",
    "ArxivClient",
]
