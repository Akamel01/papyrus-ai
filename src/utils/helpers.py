"""
SME Research Assistant - Utilities

Common helper functions used across the system.
"""

import hashlib
import re
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from functools import lru_cache


@lru_cache(maxsize=1)
def load_config(config_path: str = "config/config.yaml") -> Dict[str, Any]:
    """
    Load and cache configuration from YAML file.

    Environment variable references in the format ${VAR_NAME} are
    automatically resolved at load time. This enables secure credential
    management where secrets are stored in .env files rather than
    in the config YAML.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # Resolve ${VAR} references from environment variables
    from src.utils.env_resolver import resolve_env_vars
    config = resolve_env_vars(config)

    return config


@lru_cache(maxsize=1)
def load_prompts(prompts_path: str = "config/prompts.yaml") -> Dict[str, Any]:
    """Load and cache prompt templates from YAML file."""
    path = Path(prompts_path)
    if not path.exists():
        raise FileNotFoundError(f"Prompts file not found: {prompts_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def extract_doi_from_filename(filename: str) -> Optional[str]:
    """
    Extract DOI from filename.
    
    Example: "10.1001_jama.2013.491.pdf" -> "10.1001/jama.2013.491"
    """
    # Remove .pdf extension
    name = filename.replace('.pdf', '').replace('.PDF', '')
    
    # Replace underscore with slash for DOI format
    # DOI format: 10.PREFIX/SUFFIX
    if name.startswith('10.'):
        # Find the first underscore after 10.XXXX
        parts = name.split('_', 1)
        if len(parts) == 2:
            return f"{parts[0]}/{parts[1]}"
    
    return name  # Return as-is if can't parse


def generate_chunk_id(doi: str, section: str, chunk_index: int) -> str:
    """Generate a unique ID for a chunk."""
    content = f"{doi}:{section}:{chunk_index}"
    return hashlib.md5(content.encode()).hexdigest()


def generate_content_hash(text: str) -> str:
    """Generate a hash of text content for deduplication."""
    # Normalize whitespace
    normalized = ' '.join(text.split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def clean_text(text: str) -> str:
    """Clean extracted text from PDF."""
    if not text:
        return ""
    
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Remove page numbers (common patterns)
    text = re.sub(r'\b\d+\s*$', '', text, flags=re.MULTILINE)
    
    # Remove common header/footer patterns
    text = re.sub(r'^\s*Page\s+\d+\s*$', '', text, flags=re.MULTILINE | re.IGNORECASE)
    
    # Remove excessive newlines but preserve paragraph breaks
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


def estimate_tokens(text: str, chars_per_token: float = 4.0) -> int:
    """Estimate token count from character count."""
    return int(len(text) / chars_per_token)


def truncate_text(text: str, max_chars: int, suffix: str = "...") -> str:
    """Truncate text to max characters, ending at word boundary."""
    if len(text) <= max_chars:
        return text
    
    truncated = text[:max_chars - len(suffix)]
    # Find last space to avoid cutting words
    last_space = truncated.rfind(' ')
    if last_space > max_chars * 0.8:  # Only if we don't lose too much
        truncated = truncated[:last_space]
    
    return truncated + suffix


def format_doi_citation(doi: str) -> str:
    """Format DOI for citation display."""
    if doi.startswith('10.'):
        return f"[{doi}]"
    return f"[DOI: {doi}]"


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    # Remove invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Limit length
    return sanitized[:200]


def batch_items(items: list, batch_size: int):
    """Yield batches of items."""
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]
