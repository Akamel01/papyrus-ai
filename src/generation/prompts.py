"""
SME Research Assistant - Prompt Templates

Prompt engineering for RAG generation.
"""

from typing import List, Dict, Any
from src.utils.helpers import load_prompts


class PromptBuilder:
    """
    Builds prompts for RAG generation.
    """
    
    DEFAULT_SYSTEM_PROMPT = """You are an expert research assistant helping users understand academic literature. 
Your knowledge comes ONLY from the provided context excerpts from academic papers.

CRITICAL RULES:
1. EVERY factual claim must cite its source using [DOI] format
2. If information is NOT in the context, say "Based on the provided sources, I cannot find information about..."
3. NEVER make up information not in the context
4. When sources conflict, present both views with their citations
5. Distinguish between "the papers state X" vs "I interpret X"

CITATION FORMAT:
- Use [DOI] after each claim, e.g., "Speed reduction shows 35% improvement [10.1001/jama.2020.12059]"
- For multiple sources: "This is supported by several studies [10.1001/jama.2020.12059, 10.1016/j.aap.2019.05.012]"
"""
    
    def __init__(self, prompts_path: str = None):
        """
        Initialize prompt builder.
        
        Args:
            prompts_path: Path to prompts YAML file
        """
        self.prompts = {}
        if prompts_path:
            try:
                self.prompts = load_prompts(prompts_path)
            except Exception:
                pass
    
    @property
    def system_prompt(self) -> str:
        """Get system prompt."""
        return self.prompts.get("system_prompt", self.DEFAULT_SYSTEM_PROMPT)
    
    def build_rag_prompt(
        self,
        query: str,
        context: str,
        conversation_history: List[Dict[str, str]] = None
    ) -> str:
        """
        Build a RAG prompt with context.
        
        Args:
            query: User query
            context: Retrieved context string
            conversation_history: Previous messages
            
        Returns:
            Formatted prompt
        """
        parts = []
        
        # Add context
        parts.append("Context from academic papers:")
        parts.append(context)
        parts.append("\n---\n")
        
        # Add conversation history if present
        if conversation_history:
            parts.append("Previous conversation:")
            for msg in conversation_history[-5:]:  # Last 5 messages
                role = msg.get("role", "user")
                content = msg.get("content", "")
                parts.append(f"{role.upper()}: {content}")
            parts.append("\n---\n")
        
        # Add current query
        parts.append(f"User Question: {query}")
        parts.append("\nInstructions: Answer based ONLY on the provided context. Cite every claim using [DOI]. If the information is not in the context, explicitly state this.")
        
        return "\n".join(parts)
    
    def build_reasoning_prompt(
        self,
        query: str,
        context: str
    ) -> str:
        """
        Build a prompt that encourages step-by-step reasoning.
        
        Args:
            query: User query
            context: Retrieved context
            
        Returns:
            Reasoning prompt
        """
        return f"""Context from academic papers:
{context}

---

User Question: {query}

Before answering, think through these steps:
1. What exactly is the user asking?
2. What relevant information is in the provided context?
3. Are there multiple perspectives or conflicting findings?
4. What are the limitations of the available evidence?

Now provide your answer with citations [DOI] for every claim. If information is not in the context, say so explicitly."""
    
    def build_comparative_prompt(
        self,
        query: str,
        context: str
    ) -> str:
        """
        Build a prompt for comparative queries.
        
        Args:
            query: User query about comparison
            context: Retrieved context
            
        Returns:
            Comparative prompt
        """
        return f"""Context from academic papers:
{context}

---

User Question: {query}

Please compare the different approaches or findings mentioned in the sources. Structure your response as:

1. **Overview**: Brief summary of what's being compared
2. **Comparison Table** (if applicable):
   | Aspect | Option A | Option B | Source |
   |--------|----------|----------|--------|

3. **Key Differences**: Main distinctions between approaches
4. **Consensus**: Areas where sources agree
5. **Recommendation**: Based on the evidence (with caveats)

Cite every claim with [DOI]."""
    
    def build_messages(
        self,
        query: str,
        context: str,
        conversation_history: List[Dict[str, str]] = None
    ) -> List[Dict[str, str]]:
        """
        Build message list for chat API.
        
        Args:
            query: User query
            context: Retrieved context
            conversation_history: Previous messages
            
        Returns:
            List of message dicts
        """
        messages = [
            {"role": "system", "content": self.system_prompt}
        ]
        
        # Add history
        if conversation_history:
            for msg in conversation_history[-10:]:
                messages.append(msg)
        
        # Add context and query
        user_message = f"""Context from academic papers:
{context}

---

Question: {query}

Answer based ONLY on the provided context. Cite every claim with [DOI]."""
        
        messages.append({"role": "user", "content": user_message})
        
        return messages


def create_prompt_builder(prompts_path: str = None) -> PromptBuilder:
    """Factory function to create prompt builder."""
    return PromptBuilder(prompts_path)
