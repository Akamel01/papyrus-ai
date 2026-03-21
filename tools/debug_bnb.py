
import logging
from sentence_transformers import SentenceTransformer
import torch
from transformers import BitsAndBytesConfig, AutoModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_bnb():
    model_name = "Qwen/Qwen3-Embedding-8B"
    
    logger.info("--- DEBUG: BITSANDBYTES CONFIGURATION ---")
    
    try:
        import bitsandbytes as bnb
        logger.info(f"bitsandbytes version: {bnb.__version__}")
    except ImportError:
        logger.error("bitsandbytes NOT FOUND.")
        return

    logger.info(f"CUDA Available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        logger.info(f"Device: {torch.cuda.get_device_name(0)}")
        
    # Define Quanitzation Config
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True
    )
    
    model_kwargs = {
        "torch_dtype": "auto", 
        "trust_remote_code": True,
        "quantization_config": quantization_config
    }
    
    logger.info("Attempting to load model with SentenceTransformer + BNB...")
    
    try:
        # Load Model
        sbert = SentenceTransformer(
            model_name,
            trust_remote_code=True,
            model_kwargs=model_kwargs,
            device="cuda"
        )
        logger.info("✅ Model loaded successfully!")
        
        # Check Memory
        if torch.cuda.is_available():
            Allocated = torch.cuda.memory_allocated() / 1024**3
            Reserved = torch.cuda.memory_reserved() / 1024**3
            logger.info(f"VRAM Allocated: {Allocated:.2f} GB")
            logger.info(f"VRAM Reserved:  {Reserved:.2f} GB")
            
            if Allocated > 9.0:
                logger.error("❌ MEMORY TOO HIGH (>9GB). Quantization likely FAILED.")
            else:
                logger.info("✅ Memory looks correct for 4-bit (should be ~5-6 GB).")

    except Exception as e:
        logger.error(f"❌ FAILED to load model: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_bnb()
