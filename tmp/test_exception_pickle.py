import sys
from pathlib import Path
import pickle

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.exceptions import SMEBaseException, LowQualityExtractionError
from src.pipeline.retry_policy import RetryExhausted

def test_pickling():
    print("Testing SMEBaseException...")
    e1 = SMEBaseException("Test message", {"detail": "info"})
    try:
        data1 = pickle.dumps(e1)
        e1_restored = pickle.loads(data1)
        print(f"  OK! Restored: {e1_restored.message}, {e1_restored.details}")
    except Exception as e:
        print(f"  FAILED: {e}")

    print("\nTesting LowQualityExtractionError...")
    e2 = LowQualityExtractionError("Quality is 0.5")
    try:
        data2 = pickle.dumps(e2)
        e2_restored = pickle.loads(data2)
        print(f"  OK! Restored: {e2_restored.message}")
    except Exception as e:
        print(f"  FAILED: {e}")

    print("\nTesting RetryExhausted...")
    e3 = RetryExhausted(stage="chunk", last_error=e2, retry_count=3)
    try:
        data3 = pickle.dumps(e3)
        e3_restored = pickle.loads(data3)
        print(f"  OK! Restored stage={e3_restored.stage}, count={e3_restored.retry_count}, err={e3_restored.last_error}")
    except Exception as e:
        print(f"  FAILED: {e}")

if __name__ == "__main__":
    test_pickling()
