
import logging
import sys
import torch
from sentence_transformers import models
from transformers import BitsAndBytesConfig
import gc

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def print_memory(tag):
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / (1024 ** 3)
        reserved = torch.cuda.memory_reserved() / (1024 ** 3)
        print(f"[{tag}] VRAM: Alloc={allocated:.2f}GB | Reserved={reserved:.2f}GB")
    else:
        print(f"[{tag}] CUDA not available")

def check_quantization(module):
    print("\n--- Inspecting First Linear Layer ---")
    found_4bit = False
    for name, child in module.named_modules():
        class_name = child.__class__.__name__
        if "Linear4bit" in class_name:
            print(f"✅ Found 4-bit layer: {name} ({class_name})")
            found_4bit = True
            break
        elif "Linear" in class_name:
            print(f"⚠️ Found standard layer: {name} ({class_name})")
            # Don't break immediately, keep searching in case wrapper hides it
            
    if not found_4bit:
        print("\n❌ NO 4-bit layers found! Model is NOT quantized.")
    else:
        print("\n✅ Quantization Confirmed.")

def main():
    print_memory("Start")

    model_name = "Qwen/Qwen3-Embedding-8B"
    print(f"\nLoading {model_name}...")

    # Exact logic from embedder.py
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
    )

    model_args = {
        "device_map": "auto",
        "quantization_config": quantization_config,
        "trust_remote_code": True,
        "attn_implementation": "eager" 
    }

    try:
        word_embedding_model = models.Transformer(model_name, model_args=model_args)
        print("Model instantiated.")
        print_memory("After Load")
        
        # Check actual model structure inside the wrapper
        # models.Transformer wraps AutoModel in .auto_model
        check_quantization(word_embedding_model.auto_model)

    except Exception as e:
        print(f"Error loading model: {e}")

if __name__ == "__main__":
    main()
