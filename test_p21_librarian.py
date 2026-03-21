import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.academic_v2.librarian import Librarian
from src.core.interfaces import RetrievalResult, Chunk
from src.generation.ollama_client import OllamaClient
from src.config.settings import LLM_CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

def run_test():
    print("Testing Librarian Parallel Extraction...")
    
    # In Docker, we connect to the Ollama container typically on hostname 'ollama' or from LLM_CONFIG
    host = LLM_CONFIG.get("host", "http://ollama:11434")
    model = LLM_CONFIG["models"]["generation"]
    
    print(f"Connecting to LLM {model} at {host}")
    llm = OllamaClient(model=model, host=host)
    
    librarian = Librarian(llm_client=llm)

    chunks = []
    # Create 18 chunks to generate at least 3 batches of size 6 (18 // 6 = 3, min 3 = batch size 6)
    for i in range(18):
        chunk = Chunk(
            text=f"The impact of parallel processing on processing times is extremely significant in modern AI architectures. (Batch item {i})",
            doi=f"10.1234/test.2026.{i}",
            metadata={"year": 2026, "authors": ["John Doe"], "title": f"Test Title {i}"}
        )
        chunks.append(RetrievalResult(chunk=chunk, score=0.95))

    print(f"Extracting facts from {len(chunks)} chunks...")
    facts = librarian.extract_facts_from_chunks(chunks)
    
    print(f"\nExtraction complete! Found {len(facts)} unique facts.")
    for f in facts[:5]:
        print(f" - [{f.certainty}] {f.claim_text}")
    
    if len(facts) > 5:
        print(f" - (and {len(facts) - 5} more...)")

if __name__ == "__main__":
    run_test()
