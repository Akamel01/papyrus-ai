"""
Reference Splitter for SME RAG System (Phase 21).

Post-processes references to split into:
1. Cited References - papers that were actually cited in the response text
2. Additional Sources - papers that were retrieved but not explicitly cited

Usage:
    from src.utils.reference_splitter import split_references
    cited, uncited = split_references(response_text, apa_references)
"""

import re
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


def extract_author_surname(apa_reference: str) -> str:
    """Extract the first author's surname from an APA reference.
    
    Args:
        apa_reference: Full APA reference string
        
    Returns:
        First author's surname or empty string if not found
    """
    if not apa_reference:
        return ""
    
    # Pattern: "Surname, F. N." or "Surname, F.," etc.
    # APA format starts with surname followed by comma
    match = re.match(r'^([A-Za-zÀ-ÿ\-\']+),', apa_reference.strip())
    if match:
        return match.group(1)
    
    return ""


def split_references(
    response_text: str, 
    apa_references: List[str],
    include_et_al: bool = True
) -> Tuple[List[str], List[str]]:
    """Split references into cited and uncited based on response text.
    
    Searches for author surnames in the response to determine which papers
    were actually cited using (Author, Year) format.
    
    Args:
        response_text: The LLM-generated response text
        apa_references: List of full APA reference strings
        include_et_al: Whether to also check for "et al." citations
        
    Returns:
        Tuple of (cited_references, uncited_references)
    """
    if not response_text or not apa_references:
        return [], apa_references
    
    cited_refs = []
    uncited_refs = []
    
    # Convert response to normalized form for matching
    response_lower = response_text.lower()
    
    for ref in apa_references:
        surname = extract_author_surname(ref)
        
        if not surname:
            # Can't determine author, mark as uncited
            uncited_refs.append(ref)
            continue
        
        # Check if this author is cited in the response
        surname_lower = surname.lower()
        
        # Patterns to look for:
        # 1. "Surname" alone (could be in table or parenthetical)
        # 2. "(Surname, Year)"
        # 3. "(Surname et al., Year)"
        # 4. "Surname et al."
        # 5. "Surname and OtherAuthor"
        
        is_cited = False
        
        # Check for author name in response (case-insensitive)
        if surname_lower in response_lower:
            # Verify it's not just a random word match - should be near a year
            # Pattern: surname followed by year within 30 chars
            pattern = rf'\b{re.escape(surname_lower)}\b.{{0,30}}\b(19|20)\d{{2}}\b'
            if re.search(pattern, response_lower):
                is_cited = True
        
        # Also check for numbered citation matching this reference's position
        ref_index = apa_references.index(ref) + 1  # 1-based
        if f'[{ref_index}]' in response_text:
            is_cited = True
        
        if is_cited:
            cited_refs.append(ref)
        else:
            uncited_refs.append(ref)
    
    logger.info(f"Split references: {len(cited_refs)} cited, {len(uncited_refs)} uncited")
    
    return cited_refs, uncited_refs


def split_references_by_doi(
    apa_references: List[str],
    cited_dois: set,
) -> Tuple[List[str], List[str]]:
    """P9 FIX: Split references using deterministic DOI matching.
    
    Every APA reference string ends with https://doi.org/{doi}.
    We extract the DOI and check if it's in the cited set.
    This replaces the fragile surname text-matching approach.
    
    Args:
        apa_references: List of full APA reference strings
        cited_dois: Set of DOIs that were actually cited (from Architect-assigned facts)
        
    Returns:
        Tuple of (cited_references, uncited_references)
    """
    if not apa_references:
        return [], []
    
    cited_refs = []
    uncited_refs = []
    
    for ref in apa_references:
        # Extract DOI from the reference string (always at the end as https://doi.org/...)
        doi_match = re.search(r'doi\.org/(\S+)$', ref.strip())
        ref_doi = doi_match.group(1) if doi_match else None
        
        if ref_doi and ref_doi in cited_dois:
            cited_refs.append(ref)
        else:
            uncited_refs.append(ref)
    
    logger.info(
        f"DOI-split: {len(cited_refs)} cited, {len(uncited_refs)} uncited "
        f"(from {len(cited_dois)} cited DOIs, {len(apa_references)} total refs)"
    )
    return cited_refs, uncited_refs


def format_split_references(
    cited_refs: List[str], 
    uncited_refs: List[str],
    cited_header: str = "#### References (Cited in Response)",
    uncited_header: str = "#### Additional Sources (Retrieved)"
) -> str:
    """Format split references as markdown sections.
    
    Args:
        cited_refs: List of cited APA references
        uncited_refs: List of uncited APA references
        cited_header: Header for cited section
        uncited_header: Header for uncited section
        
    Returns:
        Formatted markdown string with both sections
    """
    parts = []
    
    # Sort references by (Surname, Year)
    def get_sort_key(ref):
        surname = extract_author_surname(ref).lower()
        year_match = re.search(r'\((\d{4})\)', ref)
        year = int(year_match.group(1)) if year_match else 0
        return (surname, year)

    cited_refs = sorted(cited_refs, key=get_sort_key)
    uncited_refs = sorted(uncited_refs, key=get_sort_key)
    
    if cited_refs:
        parts.append(cited_header)
        for i, ref in enumerate(cited_refs, 1):
            parts.append(f"[{i}] {ref}\n")
    
    if uncited_refs:
        if cited_refs:
            parts.append("")  # Blank line separator
        parts.append(uncited_header)
        start_num = len(cited_refs) + 1
        for i, ref in enumerate(uncited_refs, start_num):
            parts.append(f"[{i}] {ref}\n")
    
    return "\n".join(parts)
