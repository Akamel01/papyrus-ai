#!/usr/bin/env python3
"""
SME Pipeline Monitor
Monitors GPU, CPU, and Database status every 30 seconds.
Includes processing speed calculation (Items/sec).
Usage: python scripts/monitor_status.py
"""

import time
import sqlite3
import psutil
import subprocess
import sys
import os
from datetime import datetime

DB_PATH = "data/sme.db"

class SpeedTracker:
    def __init__(self):
        self.start_count = 0
        self.start_time = time.time()
        self.last_count = 0
        self.last_time = time.time()
        self.first_run = True

    def calculate(self, current_count):
        now = time.time()
        
        # Reset if count drops (DB reset)
        if not self.first_run and current_count < self.start_count:
            self.first_run = True

        if self.first_run:
            self.start_count = current_count
            self.start_time = now
            self.last_count = current_count
            self.last_time = now
            self.first_run = False
            return "Calculating..."
            
        total_elapsed = now - self.start_time
        total_diff = current_count - self.start_count
        
        # Instantaneous (last interval)
        inst_elapsed = now - self.last_time
        inst_diff = current_count - self.last_count
        inst_rate = inst_diff / inst_elapsed if inst_elapsed > 0 else 0
        
QDRANT_HOST = "localhost"
QDRANT_PORT = 6334
COLLECTION_NAME = "sme_papers"

def get_gpu_stats():
    """Get GPU utilization using nvidia-smi."""
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total', '--format=csv,noheader,nounits'],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            gpu_util, mem_used, mem_total = result.stdout.strip().split(', ')
            return f"GPU: {gpu_util}% | VRAM: {mem_used}/{mem_total} MB"
    except FileNotFoundError:
        return "GPU: nvidia-smi not found"
    except Exception as e:
        return f"GPU Error: {str(e)[:20]}..."
    return "GPU: N/A"

def get_db_stats():
    """Get count of papers by status."""
    try:
        if not os.path.exists(DB_PATH):
            return "DB: File not found", 0

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Papers by status
        cursor.execute("SELECT status, COUNT(*) FROM papers GROUP BY status ORDER BY status")
        rows = cursor.fetchall()
        
        stats = []
        total_papers = 0
        embedded_count = 0
        
        for status, count in rows:
            stats.append(f"{status}: {count}")
            total_papers += count
            if status == 'embedded':
                embedded_count = count
            
        conn.close()
        
        return f"Papers: {total_papers} ({' | '.join(stats)})", embedded_count
    except sqlite3.Error as e:
        return f"DB Error: {e}", 0
    except Exception:
        return "DB: Unreachable", 0

def get_qdrant_count():
    """Get total points in Qdrant collection."""
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=2.0)
        info = client.get_collection(COLLECTION_NAME)
        return info.points_count
    except ImportError:
        return "Install qdrant-client"
    except Exception as e:
        return f"Qdrant Error: {str(e)[:30]}"

class SpeedTracker:
    def __init__(self, label="Items"):
        self.label = label
        self.start_count = 0
        self.start_time = time.time()
        self.last_count = 0
        self.last_time = time.time()
        self.first_run = True

    def calculate(self, current_count):
        if not isinstance(current_count, (int, float)):
             return f"{self.label}: N/A"

        now = time.time()
        
        # Reset if count drops (DB reset)
        if not self.first_run and current_count < self.start_count:
            self.first_run = True

        if self.first_run:
            self.start_count = current_count
            self.start_time = now
            self.last_count = current_count
            self.last_time = now
            self.first_run = False
            return f"{self.label}: Calculating..."
            
        total_elapsed = now - self.start_time
        total_diff = current_count - self.start_count
        
        # Instantaneous (last interval)
        inst_elapsed = now - self.last_time
        inst_diff = current_count - self.last_count
        inst_rate = inst_diff / inst_elapsed if inst_elapsed > 0 else 0
        
        if total_elapsed < 1:
            return f"{self.label}: Calculating..."

        # Cumulative Average
        avg_rate = total_diff / total_elapsed
        per_day = avg_rate * 86400
        
        self.last_count = current_count
        self.last_time = now
        
        return f"{self.label}: {inst_rate:.2f}/s (Avg: {avg_rate:.2f}/s | ~{int(per_day):,}/day)"

def main():
    import signal
    def clean_exit(signum, frame):
        print("\nMonitor stopped.")
        sys.exit(0)
    signal.signal(signal.SIGINT, clean_exit)
    
    print(f"Starting Monitor... (Ctrl+C to stop)")
    print(f"Database: {DB_PATH}")
    print(f"Qdrant: {QDRANT_HOST}:{QDRANT_PORT}")
    
    paper_tracker = SpeedTracker("Papers")
    chunk_tracker = SpeedTracker("Chunks")
    
    while True:
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cpu_util = psutil.cpu_percent(interval=1)
            ram_util = psutil.virtual_memory().percent
            
            gpu_stats = get_gpu_stats()
            db_text, db_embedded_count = get_db_stats()
            qdrant_points = get_qdrant_count()
            
            paper_speed = paper_tracker.calculate(db_embedded_count)
            chunk_speed = chunk_tracker.calculate(qdrant_points)
            
            print("\033[2J\033[H", end="") # Clear screen
            
            output = (
                f"\n=== SME Pipeline Status [{timestamp}] ===\n"
                f"SYSTEM:  CPU: {cpu_util}% | RAM: {ram_util}%\n"
                f"         {gpu_stats}\n"
                f"\n"
                f"RATE:    {paper_speed}\n"
                f"         {chunk_speed}\n"
                f"\n"
                f"DATA:    Qdrant Points: {qdrant_points}\n"
                f"         {db_text}\n"
                f"=========================================="
            )
            
            print(output)
            
            # Append to log
            with open("data/monitor.log", "a") as f:
                f.write(output + "\n")
                
            time.sleep(10) # Faster updates (10s)
            
        except Exception as e:
            print(f"Error in monitor loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
