"""
SME Research Assistant - Embedder Factory

Factory for creating Embedder instances (Remote or Local).
"""
import logging
from typing import Optional

from src.core.interfaces import Embedder

logger = logging.getLogger(__name__)

def create_embedder(
    model_name: str = "Qwen3-Embedding-8B",
    device: Optional[str] = None,
    batch_size: int = 32,
    quantization: Optional[str] = None,
    max_seq_length: int = 4096,
    remote_url: Optional[str] = None,
    enable_fallback: bool = True
) -> Embedder:
    """
    Factory function to create an embedder with automatic fallback.

    Args:
        model_name: Model identifier
        device: 'cuda' or 'cpu' (for local)
        batch_size: Batch size
        quantization: '4bit', '8bit' (for local)
        max_seq_length: Max context
        remote_url: URL for RemoteEmbedder (e.g. http://sme_ollama:11434).
                   If provided, attempts RemoteEmbedder first.
                   If None or remote fails (and enable_fallback=True),
                   falls back to local TransformerEmbedder.
        enable_fallback: If True, falls back to local on remote failure (default: True)

    Returns:
        Embedder instance (RemoteEmbedder or TransformerEmbedder)

    Raises:
        RuntimeError: If remote embedder fails and fallback is disabled
    """
    if remote_url:
        logger.info(f"Creating RemoteEmbedder for {model_name} at {remote_url}")
        try:
            # Lazy import to avoid loading http/requests unless needed
            from src.indexing.embedder_remote import RemoteEmbedder
            embedder = RemoteEmbedder(
                model_name=model_name,
                base_url=remote_url,
                batch_size=batch_size,
                max_seq_length=max_seq_length
            )
            logger.info(f"✓ RemoteEmbedder created successfully")
            return embedder

        except Exception as e:
            logger.error(f"RemoteEmbedder creation failed: {e}")
            if not enable_fallback:
                raise RuntimeError(f"RemoteEmbedder failed and fallback disabled: {e}")

            logger.warning(f"Falling back to local TransformerEmbedder due to remote failure")
            # Fall through to local embedder creation below

    logger.info(f"Creating Local TransformerEmbedder for {model_name}...")
    # Lazy import to avoid heavy libraries (torch, transformers) if using remote
    from src.indexing.embedder_local import TransformerEmbedder

    embedder = TransformerEmbedder(
        model_name=model_name,
        device=device,
        batch_size=batch_size,
        quantization=quantization,
        max_seq_length=max_seq_length
    )
    logger.info(f"✓ TransformerEmbedder created successfully")
    return embedder
