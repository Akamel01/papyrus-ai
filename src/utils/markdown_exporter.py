"""
Markdown Exporter for RAG Responses.

Formats individual answers or full conversations as clean markdown
for copying and exporting.
"""

from typing import List, Dict, Optional
from datetime import datetime


def format_answer_as_markdown(
    question: str,
    response: str,
    apa_references: List[str] = None,
    confidence: str = None,
    model: str = None,
    depth: str = None
) -> str:
    """
    Format a single Q&A exchange as markdown.
    
    Args:
        question: User's question
        response: Assistant's response
        apa_references: List of APA reference strings
        confidence: Confidence level (HIGH/MEDIUM/LOW)
        model: Model used
        depth: Research depth setting
        
    Returns:
        Formatted markdown string
    """
    lines = []
    
    # Header with metadata
    lines.append(f"## Question")
    lines.append(f"> {question}")
    lines.append("")
    
    # Response
    lines.append(f"## Answer")
    if confidence:
        lines.append(f"*Confidence: {confidence}*")
    if model and depth:
        lines.append(f"*Model: {model} | Depth: {depth}*")
    lines.append("")
    lines.append(response)
    lines.append("")
    
    # References
    if apa_references:
        lines.append("## References")
        lines.append("")
        for i, ref in enumerate(apa_references, 1):
            lines.append(f"[{i}] {ref}")
        lines.append("")
    
    return "\n".join(lines)


def format_conversation_as_markdown(
    messages: List[Dict],
    title: str = None
) -> str:
    """
    Format entire conversation history as markdown.
    
    Args:
        messages: List of message dictionaries from session_state
        title: Optional title for the document
        
    Returns:
        Formatted markdown string
    """
    lines = []
    
    # Document header
    if title:
        lines.append(f"# {title}")
    else:
        lines.append("# Research Conversation")
    
    lines.append("")
    lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Process each message
    q_num = 0
    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        content = msg.get("content", "")
        
        if role == "user":
            q_num += 1
            lines.append(f"## Question {q_num}")
            lines.append(f"> {content}")
            lines.append("")
            
        elif role == "assistant":
            lines.append(f"### Answer")
            
            # Add metadata if available
            confidence = msg.get("confidence", "")
            model = msg.get("model", "")
            depth = msg.get("depth", "")
            
            if confidence or model or depth:
                meta_parts = []
                if confidence:
                    meta_parts.append(f"Confidence: {confidence}")
                if model:
                    meta_parts.append(f"Model: {model}")
                if depth:
                    meta_parts.append(f"Depth: {depth}")
                lines.append(f"*{' | '.join(meta_parts)}*")
                lines.append("")
            
            lines.append(content)
            lines.append("")
            
            # Add references if available
            apa_refs = msg.get("apa_references", [])
            if apa_refs:
                lines.append("#### References")
                lines.append("")
                for j, ref in enumerate(apa_refs, 1):
                    lines.append(f"[{j}] {ref}")
                lines.append("")
            
            lines.append("---")
            lines.append("")
    
    return "\n".join(lines)


def escape_markdown(text: str) -> str:
    """Escape special markdown characters if needed."""
    # For now, pass through - can add escaping if needed
    return text
