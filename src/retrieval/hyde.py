"""
HyDE (Hypothetical Document Embeddings) for improved semantic retrieval.

The idea: Instead of embedding the user's short query, we first ask the LLM
to generate a "hypothetical ideal answer", then embed THAT. This produces
a vector closer to actual document content in embedding space.

Reference: https://arxiv.org/abs/2212.10496
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class HyDERetriever:
    """
    Hypothetical Document Embeddings retriever.
    """
    
    def __init__(self, llm_client, embedder, vector_store, top_k: int = 50):
        """
        Initialize HyDE retriever.
        
        Args:
            llm_client: LLM client for generating hypothetical documents
            embedder: Embedder for creating vectors
            vector_store: Vector store for searching
            top_k: Number of results to retrieve
        """
        self.llm = llm_client
        self.embedder = embedder
        self.vector_store = vector_store
        self.top_k = top_k
        
    def generate_hypothetical_document(self, query: str, model: str = None) -> str:
        """
        Generate a hypothetical document that would answer the query.
        """
        prompt = f"""You are a research paper writing assistant. Given a research question, 
write a short paragraph (3-5 sentences) that would appear in a scientific paper answering this question.
Write in academic style with technical terminology. Do not include citations or references.
Just write the content that would answer the question.

Research Question: {query}

Hypothetical Answer Paragraph:"""

        try:
            response = self.llm.generate(
                prompt=prompt,
                system_prompt="You are an expert academic writer.",
                temperature=0.3,
                max_tokens=1200,  # H2: was 300 (4×)
                model=model  # Use selected model
            )
            # Sanitize log output for Windows consoles
            safe_preview = response[:100].encode('ascii', 'replace').decode('ascii')
            logger.info(f"Generated hypothetical document: {safe_preview}...")
            return response
        except Exception as e:
            logger.warning(f"HyDE generation failed: {e}, falling back to original query")
            return query
    
    def search(self, query: str, use_hyde: bool = True, model: str = None,
               user_id: Optional[str] = None, **kwargs) -> List:
        """
        Search using HyDE methodology.

        Args:
            query: User's original query
            use_hyde: Whether to use HyDE (can be disabled for simple queries)
            model: Optional model override for LLM
            user_id: Optional user ID for multi-user isolation. If provided, only returns
                     results belonging to this user.
            **kwargs: Additional arguments passed to vector_store.search (e.g. search_params)

        Returns:
            List of RetrievalResults
        """
        if use_hyde:
            # Generate hypothetical document
            hypothetical_doc = self.generate_hypothetical_document(query, model=model)
            # Embed the hypothetical document instead of the query
            try:
                search_vector = self.embedder.embed_query(hypothetical_doc)
            except AttributeError:
                # Handle case where embedder might be inside a HybridSearch wrapper or similar
                if hasattr(self.embedder, "embed_query"):
                    search_vector = self.embedder.embed_query(hypothetical_doc)
                else:
                    search_vector = self.embedder.embed(hypothetical_doc)
        else:
            # Standard embedding of query
            try:
                search_vector = self.embedder.embed_query(query)
            except AttributeError:
                 if hasattr(self.embedder, "embed_query"):
                    search_vector = self.embedder.embed_query(query)
                 else:
                    search_vector = self.embedder.embed(query)

        # MULTI-USER: Build filters for user isolation
        filters = kwargs.pop("filters", None)
        if user_id:
            filters = filters.copy() if filters else {}
            filters["user_id"] = user_id
            logger.debug(f"[HyDE] User isolation active: user_id={user_id}")

        # Search vector store
        results = self.vector_store.search(
            query_embedding=search_vector,
            top_k=self.top_k,
            filters=filters,
            **kwargs
        )

        return results


def create_hyde_retriever(llm_client, embedder, vector_store, top_k: int = 100):
    """Factory function to create HyDE retriever."""
    return HyDERetriever(
        llm_client=llm_client,
        embedder=embedder,
        vector_store=vector_store,
        top_k=top_k
    )
