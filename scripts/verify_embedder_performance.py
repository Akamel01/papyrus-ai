import time
import torch
import logging
import sys
import os

# Ensure src is found
sys.path.append(os.getcwd())

from src.indexing.embedder import TransformerEmbedder

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def print_gpu_memory(tag=""):
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        print(f"[{tag}] GPU Memory: Allocated: {allocated:.2f} GB, Reserved: {reserved:.2f} GB")
    else:
        print(f"[{tag}] CUDA not available.")

def main():
    print("\n===========================================")
    print("   Starting Embedder Verification Logic")
    print("===========================================\n")
    print_gpu_memory("Start")
    
    start_time = time.time()
    
    # Instantiate with exact key parameters
    model_name = "Qwen/Qwen3-Embedding-8B"
    device = "cuda"
    quantization = "4bit"
    
    print(f"Config: Model={model_name}, Device={device}, Quantization={quantization}")

    try:
        print("Instantiating TransformerEmbedder...")
        embedder = TransformerEmbedder(
            model_name=model_name,
            device=device,
            quantization=quantization
        )
        print("Embedder Instantiated.")
        print_gpu_memory("After Instantiation")

        print("\nLoading Model (This should trigger the heavy load)...")
        load_start = time.time()
        embedder.load()
        load_end = time.time()
        
        print(f"\n✅ Model Loaded Successfully in {load_end - load_start:.2f} seconds.")
        print_gpu_memory("After Load")
        
        # Test a dummy embedding to ensure it works
        print("\nTesting Inference...")
        vec = embedder.embed("Hello world. This is a test.")
        print(f"Inference successful. Vector dimension: {len(vec)}")
        print_gpu_memory("After Inference")

    except Exception as e:
        logger.error(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
