"""
Query Expansion and Decomposition for complex research questions.

For multi-part or comparative questions, this module decomposes them into
sub-queries that can be searched independently, then merged.
"""

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)


class QueryExpander:
    """
    Expands and decomposes complex queries into sub-queries.
    """
    
    def __init__(self, llm_client=None):
        """
        Initialize query expander.
        
        Args:
            llm_client: Optional LLM for intelligent decomposition
        """
        self.llm = llm_client
        
    def is_complex_query(self, query: str) -> bool:
        """
        Detect if a query is complex (multi-part, comparative, etc.)
        """
        # Heuristics for complex queries
        complex_indicators = [
            r'\b(and|or|versus|vs\.?|compared to|difference between)\b',
            r'\b(what are|list|enumerate|identify all)\b',
            r'\?.*\?',  # Multiple question marks
            len(query.split()) > 15  # Long queries
        ]
        
        for pattern in complex_indicators[:-1]:
            if re.search(pattern, query, re.IGNORECASE):
                return True
        
        return complex_indicators[-1]  # Length check
    
    def decompose_query(self, query: str, model: str = None, min_queries: int = 1, max_queries: int = 5) -> List[str]:
        """
        Decompose a complex query into sub-queries.
        
        Args:
            query: The user's question
            model: Optional model override
            min_queries: Minimum number of sub-queries required.
            max_queries: Maximum number of sub-queries allowed.
        
        Returns:
            List of sub-queries to search independently
        """
        # If min=1 and max=1, just return original (bypass LLM cost)
        if max_queries == 1:
            return [query]
            
        # If we need multiple queries (min > 1), we skip heuristics and force decomposition.
        # Functionally equivalent to the old "force_complex" behavior but cleaner.
        if min_queries == 1 and not self.is_complex_query(query):
             return [query]

        if self.llm:
            return self._llm_decompose(query, model=model, min_q=min_queries, max_q=max_queries)
        else:
            return self._rule_based_decompose(query, min_q=min_queries)
    
    def _rule_based_decompose(self, query: str, min_q: int = 1) -> List[str]:
        """
        Simple rule-based query decomposition.
        """
        sub_queries = [query]  # Always include original
        
        # Split on "and" for conjunctive queries
        if ' and ' in query.lower():
            parts = re.split(r'\s+and\s+', query, flags=re.IGNORECASE)
            sub_queries.extend([p.strip() for p in parts if len(p.strip()) > 10])
            
        # Split on "versus/vs" for comparative queries
        if re.search(r'\b(versus|vs\.?)\b', query, re.IGNORECASE):
            parts = re.split(r'\s+(versus|vs\.?)\s+', query, flags=re.IGNORECASE)
            # Filter out the separator itself
            parts = [p for p in parts if p.lower() not in ['versus', 'vs', 'vs.']]
            sub_queries.extend([p.strip() for p in parts if len(p.strip()) > 5])
            
        results = list(set(sub_queries))  # Deduplicate
        
        # Fallback padding if strict min required (duplicate original to meet count)
        # Rule-based can't invent new queries easily.
        while len(results) < min_q:
             results.append(query) # Duplicate original
             
        return results
    
    def _llm_decompose(self, query: str, model: str = None, min_q: int = 1, max_q: int = 5) -> List[str]:
        """
        Use LLM for intelligent query decomposition with count constraints.
        """
        prompt = f"""Analyze this research question and break it into independent sub-questions 
that can be searched separately. 

CONSTRAINTS:
- You MUST return between {min_q} and {max_q} sub-questions.
- Return only the sub-questions, one per line.
- {f"Since min={min_q}, you MUST break it down." if min_q > 1 else "If simple, return original."}

Original Question: {query}

Sub-questions (one per line):"""

        try:
            response = self.llm.generate(
                prompt=prompt,
                system_prompt="You are a research methodology expert.",
                temperature=0.1,
                max_tokens=800,  # H2: was 200 (4×)
                model=model  # Use selected model
            )
            
            # Parse response into list
            sub_queries = [q.strip() for q in response.strip().split('\n') if q.strip()]
            # Filter out numbering and bullets
            sub_queries = [re.sub(r'^[\d\.\-\*]+\s*', '', q) for q in sub_queries]
            sub_queries = [q for q in sub_queries if len(q) > 10]
            
            if sub_queries:
                return sub_queries
            else:
                # If LLM failed to produce valid list, fallback
                return self._rule_based_decompose(query, min_q)
                
        except Exception as e:
            logger.warning(f"LLM decomposition failed: {e}")
            return self._rule_based_decompose(query, min_q)
    
    def expand_with_synonyms(self, query: str) -> List[str]:
        """
        Expand query with domain-specific synonyms.
        """
        # Domain-specific synonym map for road safety
        synonym_map = {
            'crash': ['accident', 'collision', 'incident'],
            'safety': ['risk', 'hazard', 'protection'],
            'autonomous': ['self-driving', 'automated', 'driverless'],
            'pedestrian': ['walker', 'foot traffic'],
            'intersection': ['junction', 'crossing'],
            'ttc': ['time-to-collision', 'time to collision'],
        }
        
        expanded = [query]
        query_lower = query.lower()
        
        for term, synonyms in synonym_map.items():
            if term in query_lower:
                for syn in synonyms:
                    expanded_query = re.sub(
                        rf'\b{term}\b', 
                        syn, 
                        query, 
                        flags=re.IGNORECASE
                    )
                    if expanded_query != query:
                        expanded.append(expanded_query)
                        
        return expanded[:3]  # Limit expansion


def create_query_expander(llm_client=None):
    """Factory function to create query expander."""
    return QueryExpander(llm_client=llm_client)
