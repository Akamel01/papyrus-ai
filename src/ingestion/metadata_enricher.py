"""
Inline Metadata Enricher for SME RAG System.

This module provides automatic metadata enrichment during ingestion.
It queries OpenAlex API to fetch bibliographic information and formats APA references.

Integration:
- Call `enrich_batch_sync()` after upserting each batch to Qdrant
- Or call `enrich_all_missing()` periodically to catch any papers without metadata
"""

import logging
import time
from typing import List, Dict, Set, Optional
import requests
from requests.adapters import HTTPAdapter, Retry

logger = logging.getLogger(__name__)

OPENALEX_API_URL = "https://api.openalex.org/works"


def format_author_apa(name: str) -> str:
    """Convert 'John Adam Smith' to 'Smith, J. A.'"""
    if not name:
        return ""
    parts = name.strip().split()
    if len(parts) == 1:
        return parts[0]
    last_name = parts[-1]
    initials = ". ".join([p[0] + "." for p in parts[:-1]])
    return f"{last_name}, {initials}"


def format_apa_reference(authors: List[str], year: int, title: str, journal: str,
                         volume: str, issue: str, first_page: str, last_page: str,
                         doi: str) -> str:
    """Format metadata into APA 7 reference string."""
    # Format authors
    if not authors:
        author_str = "Unknown Author"
    elif len(authors) == 1:
        author_str = format_author_apa(authors[0])
    elif len(authors) == 2:
        author_str = f"{format_author_apa(authors[0])}, & {format_author_apa(authors[1])}"
    elif len(authors) <= 20:
        formatted = [format_author_apa(a) for a in authors]
        author_str = ", ".join(formatted[:-1]) + ", & " + formatted[-1]
    else:
        formatted = [format_author_apa(a) for a in authors[:19]]
        author_str = ", ".join(formatted) + ", ... " + format_author_apa(authors[-1])
    
    # Volume/Issue
    vol_issue = ""
    if volume:
        vol_issue = f"{volume}"
        if issue:
            vol_issue += f"({issue})"
    
    # Pages
    pages = ""
    if first_page and last_page:
        pages = f", {first_page}-{last_page}"
    elif first_page:
        pages = f", {first_page}"
    
    # Assemble
    ref_parts = [f"{author_str} ({year})."]
    if title:
        ref_parts.append(f"{title}.")
    if journal:
        if vol_issue:
            ref_parts.append(f"{journal}, {vol_issue}{pages}.")
        else:
            ref_parts.append(f"{journal}{pages}.")
    if doi:
        ref_parts.append(f"https://doi.org/{doi}")
    
    return " ".join(ref_parts)


def fetch_metadata_from_openalex(dois: List[str], email: str = "researcher@example.com") -> Dict[str, Dict]:
    """
    Fetch metadata for a batch of DOIs from OpenAlex.
    
    Args:
        dois: List of DOI strings (e.g., "10.1016/j.aap.2020.105722")
        email: Email for polite pool access
        
    Returns:
        Dictionary mapping DOI -> metadata dict
    """
    valid_dois = [d for d in dois if d.startswith("10.")]
    if not valid_dois:
        return {}
    
    doi_map = {}
    batch_size = 40
    
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    
    for i in range(0, len(valid_dois), batch_size):
        batch = valid_dois[i:i+batch_size]
        doi_filter = "|".join([f"https://doi.org/{doi}" for doi in batch])
        
        try:
            url = f"{OPENALEX_API_URL}?filter=doi:{doi_filter}&per-page=50"
            resp = session.get(url, params={"mailto": email}, timeout=15)
            
            if resp.status_code == 200:
                data = resp.json()
                for work in data.get('results', []):
                    work_doi = work.get('doi', '').replace('https://doi.org/', '').lower()
                    
                    authorships = work.get('authorships', [])
                    author_names = [a.get('author', {}).get('display_name', '') for a in authorships]
                    author_last_names = [n.split()[-1] if n else '' for n in author_names]
                    
                    # Short citation
                    if len(author_last_names) > 2:
                        short_citation = f"{author_last_names[0]} et al."
                    elif len(author_last_names) == 2:
                        short_citation = f"{author_last_names[0]} & {author_last_names[1]}"
                    elif len(author_last_names) == 1:
                        short_citation = author_last_names[0]
                    else:
                        short_citation = "Unknown Author"
                    
                    year = work.get('publication_year')
                    short_citation += f" ({year})"
                    
                    # Bibliographic details
                    biblio = work.get('biblio', {})
                    volume = biblio.get('volume', '')
                    issue = biblio.get('issue', '')
                    first_page = biblio.get('first_page', '')
                    last_page = biblio.get('last_page', '')
                    
                    primary_loc = work.get('primary_location', {})
                    source = primary_loc.get('source', {})
                    venue = source.get('display_name', '')
                    title = work.get('title', '')
                    
                    apa_ref = format_apa_reference(
                        authors=author_names, year=year, title=title,
                        journal=venue, volume=volume, issue=issue,
                        first_page=first_page, last_page=last_page, doi=work_doi
                    )
                    
                    doi_map[work_doi] = {
                        "title": title,
                        "authors": author_names,
                        "year": year,
                        "venue": venue,
                        "volume": volume,
                        "issue": issue,
                        "first_page": first_page,
                        "last_page": last_page,
                        "citation_str": short_citation,
                        "apa_reference": apa_ref
                    }
            
            time.sleep(0.1)
            
        except Exception as e:
            logger.warning(f"OpenAlex fetch failed for batch: {e}")
    
    return doi_map


def enrich_batch_sync(qdrant_client, collection_name: str, dois: List[str]) -> int:
    """
    Synchronously enrich a batch of DOIs in Qdrant.
    Call this AFTER upserting papers to ensure they have metadata.
    
    Args:
        qdrant_client: QdrantClient instance
        collection_name: Name of the collection
        dois: List of DOIs to enrich
        
    Returns:
        Number of papers enriched
    """
    from qdrant_client.http import models
    
    if not dois:
        return 0
    
    # Fetch metadata
    metadata_map = fetch_metadata_from_openalex(dois)
    
    if not metadata_map:
        return 0
    
    enriched_count = 0
    for doi, meta in metadata_map.items():
        try:
            qdrant_client.set_payload(
                collection_name=collection_name,
                payload={
                    "title": meta['title'],
                    "authors": meta['authors'],
                    "year": meta['year'],
                    "venue": meta['venue'],
                    "volume": meta.get('volume', ''),
                    "issue": meta.get('issue', ''),
                    "first_page": meta.get('first_page', ''),
                    "last_page": meta.get('last_page', ''),
                    "citation_str": meta['citation_str'],
                    "apa_reference": meta.get('apa_reference', '')
                },
                points=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="doi",
                            match=models.MatchValue(value=doi)
                        )
                    ]
                )
            )
            enriched_count += 1
        except Exception as e:
            logger.warning(f"Failed to enrich DOI {doi}: {e}")
    
    return enriched_count


def find_unenriched_dois(qdrant_client, collection_name: str, sample_size: int = 1000) -> Set[str]:
    """
    Find DOIs in the collection that don't have APA metadata yet.
    
    Args:
        qdrant_client: QdrantClient instance
        collection_name: Name of the collection
        sample_size: Number of points to sample
        
    Returns:
        Set of DOIs without enrichment
    """
    unenriched = set()
    
    try:
        points, _ = qdrant_client.scroll(
            collection_name=collection_name,
            limit=sample_size,
            with_payload=True,
            with_vectors=False
        )
        
        for point in points:
            payload = point.payload or {}
            # Check if paper lacks APA reference
            if payload.get('doi') and not payload.get('apa_reference'):
                unenriched.add(payload['doi'])
                
    except Exception as e:
        logger.error(f"Failed to find unenriched DOIs: {e}")
    
    return unenriched


def enrich_all_missing(qdrant_client, collection_name: str = "sme_papers") -> int:
    """
    Find and enrich all papers missing APA metadata.
    Call this as a background job or after major ingestion runs.
    
    Returns:
        Number of papers enriched
    """
    logger.info("Scanning for unenriched papers...")
    
    # Scroll through all papers to find those without metadata
    all_unenriched = set()
    offset = None
    batch_size = 1000
    
    while True:
        points, next_offset = qdrant_client.scroll(
            collection_name=collection_name,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False
        )
        
        for point in points:
            payload = point.payload or {}
            if payload.get('doi') and not payload.get('apa_reference'):
                all_unenriched.add(payload['doi'])
        
        offset = next_offset
        if offset is None:
            break
    
    logger.info(f"Found {len(all_unenriched)} papers without metadata")
    
    if not all_unenriched:
        return 0
    
    # Enrich in batches
    total_enriched = 0
    doi_list = list(all_unenriched)
    batch_size = 100
    
    for i in range(0, len(doi_list), batch_size):
        batch = doi_list[i:i+batch_size]
        count = enrich_batch_sync(qdrant_client, collection_name, batch)
        total_enriched += count
        logger.info(f"Enriched {total_enriched}/{len(doi_list)} papers...")
    
    return total_enriched
