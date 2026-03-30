import psutil
import sys
import signal
import os

def stop_pipeline():
    print("Searching for pipeline process...")
    found = False
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            # Check for python process running autonomous_update.py
            cmdline = proc.info['cmdline']
            if cmdline and 'python' in cmdline[0] and any('autonomous_update.py' in arg for arg in cmdline):
                pid = proc.info['pid']
                print(f"Found pipeline process (PID: {pid}). Sending SIGINT to process group...")
                
                # Send SIGINT (CTRL+C) to entire process group to allow graceful shutdown
                try:
                    os.killpg(os.getpgid(pid), signal.SIGINT)
                except (AttributeError, ProcessLookupError):
                    proc.send_signal(signal.SIGINT)
                found = True
                
                try:
                    # Wait indefinitely for graceful shutdown
                    print(f"Waiting for process {pid} to shutdown gracefully (this may take time)...")
                    proc.wait() 
                    print(f"Process {pid} terminated successfully.")
                except psutil.NoSuchProcess:
                    # Process might have died immediately
                    print(f"Process {pid} terminated successfully.")
                    
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
            
    if not found:
        print("No active pipeline process found.")

if __name__ == "__main__":
    stop_pipeline()
