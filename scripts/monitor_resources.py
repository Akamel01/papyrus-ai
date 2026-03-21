#!/usr/bin/env python3
"""
Resource monitor for streaming pipeline diagnosis.
Runs INSIDE the sme_app container alongside the pipeline.
Logs system/GPU metrics every 10s to data/resource_monitor.csv

Usage:
  docker exec sme_app python scripts/monitor_resources.py &
  (then start the pipeline)
"""

import os, sys, time, csv, subprocess, threading, signal, traceback
from datetime import datetime, timezone

LOG_PATH = "data/resource_monitor.csv"
INTERVAL = 10  # seconds

# ── Helpers ──────────────────────────────────────────────────────

def get_memory_info():
    """Read /proc/meminfo for RAM stats (Linux/Docker)."""
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    info[key] = int(parts[1])  # in kB
        total_mb = info.get("MemTotal", 0) / 1024
        avail_mb = info.get("MemAvailable", info.get("MemFree", 0)) / 1024
        buffers_mb = info.get("Buffers", 0) / 1024
        cached_mb = info.get("Cached", 0) / 1024
        used_mb = total_mb - avail_mb
        return {
            "ram_total_mb": round(total_mb, 1),
            "ram_used_mb": round(used_mb, 1),
            "ram_avail_mb": round(avail_mb, 1),
            "ram_buffers_mb": round(buffers_mb, 1),
            "ram_cached_mb": round(cached_mb, 1),
            "ram_pct": round(used_mb / total_mb * 100, 1) if total_mb > 0 else 0,
        }
    except Exception as e:
        return {"ram_total_mb": 0, "ram_used_mb": 0, "ram_avail_mb": 0,
                "ram_buffers_mb": 0, "ram_cached_mb": 0, "ram_pct": 0}


def get_process_memory():
    """Get sme_app Python process RSS from /proc/self/status."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)  # kB → MB
    except:
        pass
    return 0


def get_pipeline_processes_memory():
    """Get total RSS of all python processes (the pipeline workers)."""
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5
        )
        total_rss = 0
        count = 0
        for line in result.stdout.strip().split("\n")[1:]:
            parts = line.split(None, 10)
            if len(parts) >= 11 and "python" in parts[10].lower():
                rss_kb = int(parts[5]) if parts[5].isdigit() else 0
                total_rss += rss_kb
                count += 1
        return {"py_procs": count, "py_rss_mb": round(total_rss / 1024, 1)}
    except:
        return {"py_procs": 0, "py_rss_mb": 0}


def get_gpu_info():
    """Query nvidia-smi for GPU stats."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(",")
            return {
                "gpu_vram_used_mb": int(parts[0].strip()),
                "gpu_vram_total_mb": int(parts[1].strip()),
                "gpu_util_pct": int(parts[2].strip()),
                "gpu_temp_c": int(parts[3].strip()),
            }
    except:
        pass
    return {"gpu_vram_used_mb": 0, "gpu_vram_total_mb": 0, "gpu_util_pct": 0, "gpu_temp_c": 0}


def get_disk_io():
    """Read /proc/diskstats for I/O counters."""
    try:
        with open("/proc/diskstats") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 14 and parts[2] in ("sda", "nvme0n1", "vda"):
                    return {
                        "disk_reads": int(parts[3]),
                        "disk_writes": int(parts[7]),
                        "disk_read_sectors": int(parts[5]),
                        "disk_write_sectors": int(parts[9]),
                    }
    except:
        pass
    return {"disk_reads": 0, "disk_writes": 0, "disk_read_sectors": 0, "disk_write_sectors": 0}


def get_disk_usage():
    """Get disk usage of key directories."""
    try:
        st = os.statvfs("/app/data")
        total_gb = (st.f_blocks * st.f_frsize) / (1024**3)
        free_gb = (st.f_bavail * st.f_frsize) / (1024**3)
        used_gb = total_gb - free_gb
        return {
            "disk_total_gb": round(total_gb, 1),
            "disk_used_gb": round(used_gb, 1),
            "disk_free_gb": round(free_gb, 1),
        }
    except:
        return {"disk_total_gb": 0, "disk_used_gb": 0, "disk_free_gb": 0}


def get_open_files():
    """Count open file descriptors for current process."""
    try:
        return len(os.listdir("/proc/self/fd"))
    except:
        return 0


def get_thread_count():
    """Count threads in current process."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("Threads:"):
                    return int(line.split()[1])
    except:
        pass
    return 0


# ── Main Loop ────────────────────────────────────────────────────

stop_event = threading.Event()

def signal_handler(sig, frame):
    print(f"\n[monitor] Caught signal {sig}, stopping...")
    stop_event.set()

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def main():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    fields = [
        "timestamp", "elapsed_s",
        "ram_total_mb", "ram_used_mb", "ram_avail_mb", "ram_pct",
        "ram_buffers_mb", "ram_cached_mb",
        "py_procs", "py_rss_mb",
        "gpu_vram_used_mb", "gpu_vram_total_mb", "gpu_util_pct", "gpu_temp_c",
        "disk_total_gb", "disk_used_gb", "disk_free_gb",
        "disk_reads", "disk_writes", "disk_read_sectors", "disk_write_sectors",
        "open_fds", "threads",
    ]

    with open(LOG_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

    start = time.monotonic()
    prev_disk = get_disk_io()
    print(f"[monitor] Logging to {LOG_PATH} every {INTERVAL}s. Ctrl-C to stop.")

    while not stop_event.is_set():
        try:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            elapsed = round(time.monotonic() - start, 1)

            mem = get_memory_info()
            py = get_pipeline_processes_memory()
            gpu = get_gpu_info()
            disk_usage = get_disk_usage()
            disk_io = get_disk_io()

            # Calculate delta I/O
            delta_reads = disk_io["disk_reads"] - prev_disk["disk_reads"]
            delta_writes = disk_io["disk_writes"] - prev_disk["disk_writes"]
            delta_read_sectors = disk_io["disk_read_sectors"] - prev_disk["disk_read_sectors"]
            delta_write_sectors = disk_io["disk_write_sectors"] - prev_disk["disk_write_sectors"]
            prev_disk = disk_io

            row = {
                "timestamp": now, "elapsed_s": elapsed,
                **mem, **py, **gpu, **disk_usage,
                "disk_reads": delta_reads, "disk_writes": delta_writes,
                "disk_read_sectors": delta_read_sectors, "disk_write_sectors": delta_write_sectors,
                "open_fds": get_open_files(), "threads": get_thread_count(),
            }

            with open(LOG_PATH, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writerow(row)

            # Also print a summary line
            print(f"[{now}] RAM:{mem['ram_used_mb']:.0f}/{mem['ram_total_mb']:.0f}MB({mem['ram_pct']}%) "
                  f"PyRSS:{py['py_rss_mb']:.0f}MB GPU:{gpu['gpu_vram_used_mb']}/{gpu['gpu_vram_total_mb']}MB({gpu['gpu_util_pct']}%) "
                  f"Disk:{disk_usage['disk_used_gb']:.1f}/{disk_usage['disk_total_gb']:.1f}GB "
                  f"IO:R{delta_reads}/W{delta_writes} FDs:{row['open_fds']} Thr:{row['threads']}")

        except Exception as e:
            print(f"[monitor] Error: {e}")
            traceback.print_exc()

        stop_event.wait(INTERVAL)

    print(f"[monitor] Stopped. Data saved to {LOG_PATH}")


if __name__ == "__main__":
    main()
