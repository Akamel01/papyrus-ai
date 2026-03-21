
import time
import torch
import logging
import sys
import os

# Ensure src is found
sys.path.append(os.getcwd())

from src.indexing.embedder import QuantizedTransformer
from transformers import BitsAndBytesConfig

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def print_gpu_memory(tag=""):
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        print(f"[{tag}] VRAM: Alloc={allocated:.2f}GB | Reserved={reserved:.2f}GB")
    else:
        print(f"[{tag}] CUDA not available.")

def main():
    print("===========================================")
    print("   4-bit Loading Verification (Simple)")
    print("===========================================")
    print_gpu_memory("Start")
    
    model_name = "Qwen/Qwen3-Embedding-8B"
    print(f"\nModel: {model_name}")
    print("Quantization: 4-bit (via QuantizedTransformer)")
    
    # 4-bit Config
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True
    )
    
    # Args exactly as in embedder.py (Production Logic)
    model_kwargs = {
        "torch_dtype": "auto",
        "trust_remote_code": True,
        "low_cpu_mem_usage": True,
        "device_map": {"": "cuda:0"},
        "quantization_config": quantization_config
    }

    start_time = time.time()
    try:
        print("\n[Action] Loading Model...")
        model = QuantizedTransformer(
            model_name_or_path=model_name,
            model_args=model_kwargs
        )
        end_time = time.time()
        print(f"\n✅ Load Complete!")
        print(f"⏱️ Time Taken: {end_time - start_time:.2f} seconds ({ (end_time - start_time)/60:.2f} mins)")
        print_gpu_memory("Final")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
