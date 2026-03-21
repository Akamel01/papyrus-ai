
import sys
import logging
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline.loader import load_rag_pipeline_core

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TestStartup")

def main():
    logger.info("Starting Headless Startup Test...")
    
    try:
        # Load Pipeline (Headless Mode)
        # This will trigger:
        # 1. Embedder Load (with our new QuantizedTransformer diagnostics)
        # 2. Reranker Load (with our fix)
        pipeline = load_rag_pipeline_core(headless=True)
        
        logger.info("Pipeline Loaded Successfully!")
        
        # Keep process alive briefly to measure memory
        import torch
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated() / (1024**3)
            reserved = torch.cuda.memory_reserved() / (1024**3)
            logger.info(f"Final VRAM Usage: Alloc={allocated:.2f}GB | Reserved={reserved:.2f}GB")
        
        # Optional: Run a dummy query to verify
        # pipeline["retriever"].retrieve("test query")
        
    except Exception as e:
        logger.error(f"Startup Test Failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
