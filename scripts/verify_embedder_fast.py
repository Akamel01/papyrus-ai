
import time
import torch
import logging
import sys
import os

# Ensure src is found
sys.path.append(os.getcwd())

from src.indexing.embedder import TransformerEmbedder, QuantizedTransformer
from transformers import AutoModel, AutoConfig

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MONKEY PATCH to remove low_cpu_mem_usage
def patched_load_model(self, model_name_or_path, config=None, cache_dir=None, *args, **kwargs):
    logger.info(f"PATCHED QuantizedTransformer loading {model_name_or_path}...")
    
    # Extract quantization_config explicitly from kwargs
    quantization_config = kwargs.pop("quantization_config", None)
    
    # If config is not provided, load it
    if not config:
        config = AutoConfig.from_pretrained(model_name_or_path, cache_dir=cache_dir, **kwargs)
        
    # Log if we are quantizing
    if quantization_config:
        logger.info(f"✅ Applying BitsAndBytesConfig: {quantization_config}")

    # Explicitly load AutoModel with quantization_config
    # WE REMOVED 'low_cpu_mem_usage' from the caller (embedder.py) dictionary before calling this? 
    # No, embedder.py calls this with kwargs.
    # We need to filter kwargs here or patch the CALLER.
    
    # Actually, verify_embedder_performance.py calls TransformerEmbedder.load().
    # TransformerEmbedder.load() calls _load_model() with hardcoded kwargs.
    # So we need to patch TransformerEmbedder._load_model, NOT QuantizedTransformer._load_model.
    # Wait, TransformerEmbedder._load_model creates the model_kwargs.
    pass

# Let's verify by subclassing TransformerEmbedder in this script and overriding _load_model
class FastTransformerEmbedder(TransformerEmbedder):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_folder = None

    def _load_model(self):
        """Lazy load the model WITHOUT low_cpu_mem_usage=True."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                import torch
                
                logger.info(f"Loading embedding model: {self.model_name} on {self.device}")
                
                # MODIFIED: Removed low_cpu_mem_usage
                model_kwargs = {
                    "torch_dtype": "auto",
                    "trust_remote_code": True,
                    # "low_cpu_mem_usage": True,  <-- REMOVED
                    "device_map": "auto"
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
                
                # ... 8bit logic omitted for brevity ...

                # Instantiate CUSTOM Transformer
                self._model = QuantizedTransformer(
                    self.model_name,
                    # cache_folder=self.cache_folder,  <-- REMOVED (Not in production code)
                    model_args=model_kwargs,
                    tokenizer_args=None
                )
                logger.info("FastTransformerEmbedder Loaded.")
                
            except Exception as e:
                logger.error(f"Failed to load model: {e}")
                raise e

def print_gpu_memory(tag=""):
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        print(f"[{tag}] GPU Memory: Allocated: {allocated:.2f} GB, Reserved: {reserved:.2f} GB")

def main():
    print("\n===========================================")
    print("   Starting Embedder Verification (FAST)")
    print("===========================================\n")
    print_gpu_memory("Start")
    
    start_time = time.time()
    
    try:
        print("Instantiating FastTransformerEmbedder...")
        embedder = FastTransformerEmbedder(
            model_name="Qwen/Qwen3-Embedding-8B",
            device="cuda",
            quantization="4bit"
        )
        print("Embedder Instantiated.")

        print("\nLoading Model...")
        load_start = time.time()
        embedder.load()
        load_end = time.time()
        
        print(f"\n✅ Model Loaded Successfully in {load_end - load_start:.2f} seconds.")
        print_gpu_memory("After Load")

    except Exception as e:
        logger.error(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
