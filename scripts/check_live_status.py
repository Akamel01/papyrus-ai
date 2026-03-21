
import sys
import logging
import os
from pathlib import Path
from qdrant_client import QdrantClient

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from src.indexing.qdrant_optimizer import probe_hardware, get_collection_info

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_dir_size(path):
    total = 0
    with os.scandir(path) as it:
        for entry in it:
            if entry.is_file():
                total += entry.stat().st_size
            elif entry.is_dir():
                total += get_dir_size(entry.path)
    return total

def check_live_status_deep():
    print("\n=== 🔍 DEEP INSPECTION OF LIVE SYSTEM ===\n")

    # 1. Physical Storage Check
    qdrant_data_path = Path("data/qdrant/collections")
    if qdrant_data_path.exists():
        size_bytes = get_dir_size(qdrant_data_path)
        size_gb = size_bytes / (1024**3)
        print(f"💾 Physical Disk Usage (data/qdrant): {size_gb:.4f} GB")
        if size_gb > 0.1:
            print("   -> Data EXISTS on disk. If count is 0, we have a mismatch.")
    else:
        print("⚠️  Physical path 'data/qdrant/collections' NOT FOUND on host.")

    # 2. Connect to Live Qdrant
    print("\n... Connecting to Qdrant (localhost:6334) ...")
    try:
        client = QdrantClient(host="localhost", port=6334)
        collections = client.get_collections().collections
        print(f"\n📚 Found {len(collections)} Collections:")
        
        for col in collections:
            name = col.name
            info = get_collection_info(client, name)
            count = info["vector_count"]
            print(f"   - '{name}': {count:,} vectors")
            
            if count > 0:
                print(f"     ✅ This appears to be your data.")
                # Run math here if we find data
                run_math(count)
                
        if not collections:
            print("   ❌ No collections found in Qdrant API.")
            
    except Exception as e:
        print(f"❌ Failed to connect: {e}")

def run_math(count):
    # Hardcoded dim for now as we know it
    dim = 4096
    
    # Probe Hardware
    import psutil
    mem = psutil.virtual_memory()
    ram_gb = mem.available / (1024 ** 3)

    print(f"\n🧮 TIER CALCULATION for {count:,} vectors:")
    
    # Raw Size
    raw_bytes = count * dim * 4
    raw_gb = raw_bytes / (1024**3)
    
    # Budget Check
    limit_gb = ram_gb * 0.5
    
    print(f"    1. Raw Vector Size = {count:,} * {dim} * 4 bytes = {raw_gb:.4f} GB")
    print(f"    2. Available RAM   = {ram_gb:.2f} GB")
    print(f"    3. 'Luxury' Limit  = 50% of RAM            = {limit_gb:.4f} GB")
    
    if raw_gb < limit_gb:
        print(f"\n✅ RESULT: {raw_gb:.4f} GB < {limit_gb:.4f} GB")
        print("   -> TIER: LUXURY")
    else:
        print(f"\n❌ RESULT: {raw_gb:.4f} GB >= {limit_gb:.4f} GB")
        print("   -> TIER: BALANCED / CONSTRAINED")

if __name__ == "__main__":
    check_live_status_deep()
