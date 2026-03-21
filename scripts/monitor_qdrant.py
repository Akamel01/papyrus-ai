import time
import sys
from datetime import datetime
from qdrant_client import QdrantClient

def monitor_progress():
    print("Connecting to Qdrant...")
    try:
        client = QdrantClient(host="localhost", port=6333)
        collection_name = "sme_papers"
        
        # Initial check
        last_count = client.count(collection_name=collection_name, exact=True).count
        print(f"Connected! Initial Count: {last_count} vectors")
        print("-" * 50)
        print(f"{'TIMESTAMP':<20} | {'TOTAL VECTORS':<15} | {'DELTA':<10} | {'STATUS'}")
        print("-" * 50)
        
        while True:
            try:
                current_count = client.count(collection_name=collection_name, exact=True).count
                delta = current_count - last_count
                
                status_icon = "🟢" if delta > 0 else "⏳"
                if delta > 0:
                    status_msg = f"+{delta} vectors"
                else:
                    status_msg = "Waiting..."
                    
                timestamp = datetime.now().strftime("%H:%M:%S")
                
                # Print status line
                print(f"{timestamp:<20} | {current_count:<15,} | {status_msg:<10} | {status_icon}")
                
                last_count = current_count
                time.sleep(5)  # Update every 5 seconds
                
            except Exception as e:
                print(f"Error querying Qdrant: {e}")
                time.sleep(5)
                
    except Exception as e:
        print(f"Failed to connect to Qdrant: {e}")
        return

if __name__ == "__main__":
    monitor_progress()
