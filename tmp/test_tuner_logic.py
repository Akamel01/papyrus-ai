import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline.gpu_tuner import derive_startup_config

def test_tuner():
    print("Testing auto-tuner logic...")
    # Mock some cores
    cores = os.cpu_count() or 4
    print(f"Detected logical cores: {cores}")
    
    # Mock some GPU info
    gpu_info = {"vram_free_mb": 8000}
    
    config = derive_startup_config(gpu_info=gpu_info, cpu_cores=cores)
    
    print("\nDerived Config:")
    print(f"Parser Workers: {config['parser_workers']} (Expected: {cores})")
    print(f"Queue Size Parsed: {config['queue_size_parsed']} (Expected: 100)")
    print(f"Queue Size Embedded: {config['queue_size_embedded']} (Expected: 100)")
    
    assert config['parser_workers'] == cores
    assert config['queue_size_parsed'] == 100
    print("\n✅ Auto-tuner logic verification passed!")

if __name__ == "__main__":
    test_tuner()
