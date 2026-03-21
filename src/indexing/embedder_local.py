"""
SME Research Assistant - Embedder

Generates embeddings using sentence-transformers with BGE model.
"""

import logging
from typing import List, Optional
from pathlib import Path

from src.core.interfaces import Embedder
from src.core.exceptions import EmbeddingError

logger = logging.getLogger(__name__)

# START REFACTOR: Custom Transformer to force correct quantization loading
from sentence_transformers import models
from transformers import AutoModel, AutoConfig

class QuantizedTransformer(models.Transformer):
    """
    Custom Transformer module that explicitly handles quantization_config
    during AutoModel loading, bypassing SentenceTransformer's opaque handling.
    """
    def _load_model(self, model_name_or_path, config=None, cache_dir=None, *args, **kwargs):
        logger.info(f"QuantizedTransformer loading {model_name_or_path}...")
        logger.debug(f"Extra positional args: {args}")
        
        # Extract quantization_config explicitly from kwargs
        quantization_config = kwargs.pop("quantization_config", None)
        
        # If config is not provided, load it
        if not config:
            # We filter kwargs to avoid passing unknown args to AutoConfig if necessary, 
            # but usually AutoConfig ignores extras or we trust them.
            # However, if 'backend' is in kwargs, AutoConfig might complain?
            # Let's hope not.
            config = AutoConfig.from_pretrained(model_name_or_path, cache_dir=cache_dir, **kwargs)
            
        # Log if we are quantizing
        if quantization_config:
            logger.info(f"✅ Applying BitsAndBytesConfig: {quantization_config}")
        else:
            logger.warning("⚠️ No quantization_config found in kwargs!")

        # Explicitly load AutoModel with quantization_config
        self.auto_model = AutoModel.from_pretrained(
            model_name_or_path,
            config=config,
            cache_dir=cache_dir,
            quantization_config=quantization_config,
            **kwargs
        )
        logger.info("AutoModel loaded successfully.")
# END REFACTOR


class TransformerEmbedder(Embedder):
    """
    Generic Embedder using generic sentence-transformers (supports Qwen, BGE, etc.).
    """
    
    def __init__(
        self,
        model_name: str,
        device: Optional[str] = None,
        batch_size: int = 4,
        normalize: bool = True,
        quantization: Optional[str] = None,
        max_seq_length: int = 4096
    ):
        """
        Initialize embedder.
        
        Args:
            model_name: HuggingFace model name
            device: Device to use
            batch_size: Batch size
            normalize: Normalize embeddings
            quantization: "4bit", "8bit", or None
            max_seq_length: Maximum sequence length (tokens)
        """
        import torch
        if device is None:
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA GPU is required for embeddings (CPU is strictly prohibited).")
            self.device = "cuda"
        else:
            if device == "cpu":
                 raise RuntimeError("CPU device explicitly requested but strictly prohibited.")
            self.device = device
            
        self.model_name = model_name
        self.batch_size = batch_size
        self.normalize = normalize
        self.quantization = quantization
        self.max_seq_length = max_seq_length
        self._model = None
        self._dimension = None
        logger.info(f"TransformerEmbedder Initialized [ID: {id(self)}]. Model: {model_name}, Quantization: {quantization}")
    
    
    def load(self):
        """Eagerly load the model into memory."""
        logger.info(f"TransformerEmbedder.load() called [ID: {id(self)}]")
        self._load_model()
        return self

    def _load_model(self):
        """Lazy load the model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                import torch
                
                logger.info(f"Loading embedding model: {self.model_name} on {self.device}")
                
                model_kwargs = {
                    "torch_dtype": "auto",
                    "trust_remote_code": True,
                    "low_cpu_mem_usage": True,  # Critical for 8B models to avoid RAM spike
                    "device_map": "auto"       # FAST loading. QuantizedTransformer ensures it fits in VRAM.
                }
                
                if self.quantization == "4bit":
                    logger.info(f"[DEBUG-QUANT] quantization param = '{self.quantization}' -> Enabling 4-bit")
                    from transformers import BitsAndBytesConfig
                    quantization_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float16,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_use_double_quant=True
                    )
                    model_kwargs["quantization_config"] = quantization_config
                elif self.quantization == "8bit":
                    logger.info("Enabling 8-bit quantization...")
                    from transformers import BitsAndBytesConfig
                    quantization_config = BitsAndBytesConfig(
                        load_in_8bit=True
                    )
                    model_kwargs["quantization_config"] = quantization_config
                else:
                    logger.warning(f"[DEBUG-QUANT] quantization param = '{self.quantization}' -> NO quantization applied!")
                # CRITICAL: Use Custom QuantizedTransformer
                # models.Transformer(..., model_args=...) often fails to pass quantization_config correctly 
                # or SentenceTransformer overrides it.
                # Use our custom class that forces AutoModel.from_pretrained with explicit config.
                
                logger.info(f"Instantiating QuantizedTransformer explicitly with quantization={self.quantization}...")
                
                word_embedding_model = QuantizedTransformer(
                    self.model_name, 
                    max_seq_length=self.max_seq_length,
                    model_args=model_kwargs
                )

                # DIAGNOSTIC LOGGING
                try:
                    am = word_embedding_model.auto_model
                    logger.info(f"Model internal dtype: {getattr(am, 'dtype', 'unknown')}")
                    logger.info(f"Model config quantization: {getattr(am.config, 'quantization_config', 'None')}")
                    # Check first layer
                    for name, mod in am.named_modules():
                        if "Linear4bit" in str(type(mod)):
                            logger.info(f"✅ Found Linear4bit layer: {name}")
                            break
                        if "Linear" in str(type(mod)) and "4bit" not in str(type(mod)):
                            logger.info(f"⚠️ Found Standard Linear layer: {name} (Type: {type(mod)})")
                            break
                except Exception as diag_err:
                    logger.warning(f"Diagnostic logging failed: {diag_err}")
                
                pooling_model = models.Pooling(
                    word_embedding_model.get_word_embedding_dimension(),
                    pooling_mode='mean' # Default for most embedding models
                )
                
                self._model = SentenceTransformer(
                    modules=[word_embedding_model, pooling_model],
                    device=self.device
                )
                
                # ENFORCE VRAM CAP (Critical for RTX 3090)
                # The model supports 32k context, which can eat 80GB+ VRAM on long docs.
                if hasattr(self._model, "max_seq_length"):
                    if self.max_seq_length:
                        self._model.max_seq_length = self.max_seq_length
                        logger.info(f"Set model max_seq_length to {self.max_seq_length}")
                
                # Get embedding dimension
                self._dimension = self._model.get_sentence_embedding_dimension()
                logger.info(f"Model loaded. Dimension: {self._dimension}, Device: {self.device}")
                
            except Exception as e:
                raise EmbeddingError(
                    f"Failed to load embedding model: {str(e)}",
                    {"model": self.model_name, "error": str(e)}
                )

    @property
    def dimension(self) -> int:
        """Get embedding dimension."""
        if self._dimension is None:
            self._load_model()
        return self._dimension
    
    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.
        """
        if not texts:
            return []
        
        self._load_model()
        
        try:
            # Qwen/GTE models generally prefer raw text for passages
            # (No 'passage:' prefix unless specified by specific model variant)
            
            embeddings = self._model.encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=self.normalize,
                show_progress_bar=len(texts) > 100
            )
            
            return embeddings.tolist()
            
        except Exception as e:
            raise EmbeddingError(
                f"Failed to generate embeddings: {str(e)}",
                {"num_texts": len(texts), "error": str(e)}
            )
    
    def embed_query(self, query: str) -> List[float]:
        """
        Generate embedding for a query.
        """
        if not query:
            raise EmbeddingError("Query cannot be empty")
        
        self._load_model()
        
        try:
            # Standard GTE/Qwen instruction format for retrieval
            instruction = "Instruct: Given a research query, retrieve relevant academic papers.\nQuery: "
            prefixed_query = f"{instruction}{query}"
            
            embedding = self._model.encode(
                prefixed_query,
                normalize_embeddings=self.normalize
            )
            
            return embedding.tolist()
            
        except Exception as e:
            raise EmbeddingError(
                f"Failed to embed query: {str(e)}",
                {"query": query[:100], "error": str(e)}
            )
    
    def embed_batch(self, texts: List[str], show_progress: bool = True) -> List[List[float]]:
        """
        Generate embeddings with progress tracking.
        """
        if not texts:
            return []
        
        self._load_model()
        
        try:
            # Usage: Raw text for Qwen documents
            
            embeddings = self._model.encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=self.normalize,
                show_progress_bar=show_progress
            )
            
            return embeddings.tolist()
            
        except Exception as e:
            raise EmbeddingError(
                f"Batch embedding failed: {str(e)}",
                {"num_texts": len(texts), "error": str(e)}
            )

    def clear_cache(self):
        """Clear CUDA cache to free up VRAM."""
        if self.device == "cuda":
            import torch
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()


# create_embedder moved to src/indexing/embedder.py
