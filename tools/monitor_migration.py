
import time
import requests
import datetime
import subprocess
import os

# --- Configuration ---
PORT = 6334
URL = f"http://localhost:{PORT}/collections/sme_papers"
GPU_CMD = ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]
REFRESH_RATE = 5.0 # Seconds

def get_count():
    """Poll Qdrant for current points count."""
    try:
        response = requests.get(URL)
        if response.status_code == 200:
            return response.json()["result"]["points_count"]
    except Exception as e:
        return 0
    return 0

def get_gpu_stats():
    """Fetch GPU Utilization and VRAM via nvidia-smi."""
    try:
        out = subprocess.check_output(GPU_CMD, stderr=subprocess.DEVNULL).decode("utf-8").strip()
        gpu_util_str, mem_used_str, mem_total_str = out.split(",")
        return int(gpu_util_str), int(mem_used_str), int(mem_total_str)
    except Exception:
        # Fallback if nvidia-smi isn't found or accessible
        return 0, 0, 0

def get_cpu_ram_stats():
    """
    Get simple CPU/RAM stats.
    We use psutil if available (recommended), otherwise fallback.
    """
    try:
        import psutil
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        return cpu, ram.used / (1024**3), ram.total / (1024**3)
    except ImportError:
        return 0.0, 0.0, 0.0

def main():
    print("--- 📊 SME Migration Monitor (RTX 3090) ---")
    print("Watching Qdrant @ localhost:6334 | Refresh: 5s")
    
    prev_count = get_count()
    print(f"Initial Points Count: {prev_count:,}")
    
    # Header
    print("-" * 110)
    print(f"{'TIME':<10} | {'TOTAL':<10} | {'SPEED':<12} | {'GPU LOAD':<10} | {'VRAM (MB)':<16} | {'CPU%':<6} | {'RAM (GB)':<12}")
    print("-" * 110)

    try:
        while True:
            time.sleep(REFRESH_RATE)
            
            # 1. Qdrant Stats
            curr_count = get_count()
            diff = curr_count - prev_count
            rate = diff / REFRESH_RATE
            
            # 2. Hardware Stats
            gpu_util, gpu_mem, gpu_total = get_gpu_stats()
            cpu_util, ram_used, ram_total = get_cpu_ram_stats()
            
            # 3. Format & Print
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            
            line = (
                f"[{timestamp}] | "
                f"{curr_count:<10,} | "
                f"{rate:5.1f} ch/s  | "
                f"{gpu_util:<3}%       | "
                f"{gpu_mem}/{gpu_total} MB   | "
                f"{cpu_util:<4.1f}% | "
                f"{ram_used:.1f}/{ram_total:.1f} GB"
            )
            print(line)
            
            prev_count = curr_count
            
    except KeyboardInterrupt:
        print("\nMonitor Stopped.")

if __name__ == "__main__":
    main()
