
import inspect
from sentence_transformers import CrossEncoder
import torch
import gc

def print_memory():
    if torch.cuda.is_available():
        print(f"VRAM: {torch.cuda.memory_allocated()/1024**3:.2f}GB / {torch.cuda.memory_reserved()/1024**3:.2f}GB")

print("SentenceTransformers Version:", CrossEncoder.__module__.split('.')[0])
sig = inspect.signature(CrossEncoder.__init__)
print("\nCrossEncoder.__init__ Signature:")
for name, param in sig.parameters.items():
    print(f"  {name}: {param.default}")

print("\n--- Memory Test ---")
print_memory()
try:
    print("Loading with model_kwargs={'low_cpu_mem_usage': False}...")
    model = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cuda", model_kwargs={"low_cpu_mem_usage": False})
    print("Success loading with model_kwargs")
    print_memory()
    del model
    gc.collect()
    torch.cuda.empty_cache()
except Exception as e:
    print(f"Failed with model_kwargs: {e}")

try:
    print("\nLoading with automodel_args={'low_cpu_mem_usage': True}...")
    # Note: If device is set to cuda, CrossEncoder might move it.
    model = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cuda", automodel_args={"low_cpu_mem_usage": True})
    print("Success loading with automodel_args")
    print_memory()
except Exception as e:
    print(f"Failed with automodel_args: {e}")
