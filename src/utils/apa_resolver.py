"""
SME Research Assistant - APA Reference Resolver

Resolves DOIs to APA-formatted references by querying sme.db.
Enables consistent reference generation for both legacy and streaming papers.
"""

import json
import logging
import sqlite3
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class APAReferenceResolver:
    """
    Resolves DOIs to APA-formatted reference strings via sme.db lookup.
    
    This decouples reference generation from chunk metadata, enabling
    consistent APA references for both legacy and streaming papers.
    """
    
    @staticmethod
    def construct_apa_from_dict(row: Dict) -> str:
        """
        Construct an APA 7th Edition formatted reference string from a dictionary.
        Static method for reuse without DB connection.
        
        Args:
            row: Dictionary with keys: doi, title, authors (JSON or list), year, venue, metadata (dict)
        """
        # 1. Parse authors
        authors_val = row.get("authors")
        if isinstance(authors_val, list):
             authors_list = authors_val
        elif isinstance(authors_val, str):
             try:
                 authors_list = json.loads(authors_val)
             except:
                 authors_list = [authors_val]
        else:
             authors_list = []

        if not authors_list:
             authors_str = "Unknown Author"
        elif len(authors_list) == 1:
            authors_str = authors_list[0]
        elif len(authors_list) == 2:
            authors_str = f"{authors_list[0]}, & {authors_list[1]}"
        elif len(authors_list) <= 20:
            authors_str = ", ".join(authors_list[:-1]) + ", & " + authors_list[-1]
        else:
             authors_str = ", ".join(authors_list[:19]) + f", ... {authors_list[-1]}"

        # 2. Year
        year = row.get("year")
        year_str = f"({year})" if year else "(n.d.)"
        
        # 3. Title
        title = row.get("title") or "Untitled"
        title_str = title.strip()
        if not title_str.endswith("."):
            title_str += "."
        
        # 4. Venue
        venue = row.get("venue")
        venue_str = f" {venue}" if venue else ""
        
        # 5. Extract Nested Metadata
        # 'metadata' field might be a dict, JSON string, or None
        meta = row.get("metadata")
        if not meta:
            meta = {}
        elif isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except:
                meta = {}
        
        # Ensure meta is a dict
        if not isinstance(meta, dict):
            meta = {}

        volume = meta.get("volume")
        issue = meta.get("issue")
        pages = meta.get("pages")
        
        # Normalization
        if not pages and meta.get("first_page"):
             pages = f"{meta.get('first_page')}" 
             if meta.get("last_page"):
                 pages += f"-{meta.get('last_page')}"
        
        details_parts = []
        if venue_str: details_parts.append(venue_str.strip())
        
        vol_issue = ""
        if volume:
            vol_issue += f", {volume}"
            if issue: vol_issue += f"({issue})"
        if vol_issue: details_parts.append(vol_issue.strip(", "))
        
        if pages: details_parts.append(str(pages))
        
        source_str = ""
        if details_parts:
            source_str = " " + ", ".join(details_parts) + "."
            
        # 6. DOI/URL
        doi = row.get("doi")
        url = row.get("pdf_url") or row.get("url")
        
        link_str = ""
        if doi:
            link_str = f" https://doi.org/{doi}"
        elif url and "arxiv" in str(url).lower():
            link_str = f" {url}"
            
        return f"{authors_str} {year_str}. {title_str}{source_str}{link_str}"
    
    def __init__(self, db_path: str = "data/sme.db"):
        """
        Initialize the resolver.
        
        Args:
            db_path: Path to sme.db database file
        """
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            logger.warning(f"Database not found at {db_path}. References will fall back to DOI-only format.")
    
    def resolve(self, dois: List[str]) -> Dict[str, str]:
        """
        Resolve a list of DOIs to APA-formatted reference strings.
        
        Args:
            dois: List of DOI strings (without 'doi:' prefix)
            
        Returns:
            Dictionary mapping DOI -> APA reference string
        """
        if not dois:
            return {}
        
        if not self.db_path.exists():
            # Fallback: return DOI-only references
            return {doi: f"https://doi.org/{doi}" for doi in dois}
        
        result = {}
        
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Build parameterized query for batch lookup
            placeholders = ",".join("?" * len(dois))
            query = f"""
                SELECT doi, title, authors, year, venue 
                FROM papers 
                WHERE doi IN ({placeholders})
            """
            
            cursor.execute(query, dois)
            rows = cursor.fetchall()
            
            # Build result mapping
            for row in rows:
                doi = row["doi"]
                result[doi] = self._construct_apa(dict(row))
            
            conn.close()
            
            # Handle DOIs not found in database
            for doi in dois:
                if doi not in result:
                    logger.debug(f"DOI not found in sme.db: {doi}")
                    result[doi] = f"https://doi.org/{doi}"
            
        except sqlite3.Error as e:
            logger.error(f"Database error during APA resolution: {e}")
            # Fallback to DOI-only
            for doi in dois:
                if doi not in result:
                    result[doi] = f"https://doi.org/{doi}"
        
        return result
    
    
    def _construct_apa(self, row: Dict) -> str:
        """DEPRECATED: Use construct_apa_from_dict instead."""
        return self.construct_apa_from_dict(row)

    # _format_authors is no longer needed as instance method but keeping for compatibility if utilized elsewhere



def create_apa_resolver(db_path: str = "data/sme.db") -> APAReferenceResolver:
    """Factory function to create an APA reference resolver."""
    return APAReferenceResolver(db_path=db_path)
