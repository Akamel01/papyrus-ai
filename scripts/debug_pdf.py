import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.ingestion import create_parser, create_chunker

def debug_pdf(path):
    print(f"--- Debugging PDF: {path} ---")
    
    # 1. Parsing
    print("Creating parser...")
    parser = create_parser()
    try:
        print(f"Parsing file...")
        doc = parser.parse(Path(path))
    except Exception as e:
        print(f"❌ Parsing Failed: {e}")
        import traceback
        traceback.print_exc()
        return

    print(f"✅ Parse Successful")
    print(f"Title: {doc.title}")
    print(f"Total Text Length: {len(doc.full_text)} chars")
    print(f"Sections Found: {list(doc.sections.keys())}")
    
    # Print first 500 chars to check for garbage
    print(f"\n--- Start of Text ---\n{doc.full_text[:500]}\n--- End of Preview ---")

    # 2. Chunking
    print("\nCreating chunker...")
    chunker = create_chunker()
    chunks = chunker.chunk(doc)
    
    print(f"\n✅ Chunking Complete")
    print(f"Total Chunks: {len(chunks)}")
    
    for i, chunk in enumerate(chunks):
        print(f"\n[Chunk {i}] ID: {chunk.chunk_id}")
        print(f"Section: {chunk.section}")
        print(f"Length: {len(chunk.text)} chars / {chunker.count_tokens(chunk.text)} tokens")
        print(f"Content Preview: {chunk.text[:100]}...")

if __name__ == "__main__":
    target_path = "/app/DataBase/Papers/10.1007_s11222-022-10084-4.pdf"
    if not Path(target_path).exists():
        print(f"❌ Error: File not found at {target_path}")
    else:
        debug_pdf(target_path)
