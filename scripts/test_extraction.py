#!/usr/bin/env python
"""
Quick test script for PDF extraction on sample papers.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion import create_parser, create_chunker

def test_extraction():
    """Test PDF extraction on sample papers."""
    papers_dir = Path("DataBase/Papers")
    
    if not papers_dir.exists():
        print(f"❌ Papers directory not found: {papers_dir}")
        return False
    
    # Get first 5 PDFs
    pdf_files = list(papers_dir.glob("*.pdf"))[:5]
    
    if not pdf_files:
        print("❌ No PDF files found")
        return False
    
    print(f"Testing extraction on {len(pdf_files)} sample papers...\n")
    
    parser = create_parser(quality_threshold=0.5)
    chunker = create_chunker(chunk_size=800, chunk_overlap=150)
    
    success_count = 0
    
    for pdf_file in pdf_files:
        print(f"📄 {pdf_file.name}")
        try:
            # Parse PDF
            doc = parser.parse(pdf_file)
            print(f"   Title: {doc.title[:60]}...")
            print(f"   DOI: {doc.doi}")
            print(f"   Quality: {doc.extraction_quality:.2f}")
            print(f"   Sections: {list(doc.sections.keys())}")
            
            # Chunk document
            chunks = chunker.chunk(doc)
            print(f"   Chunks: {len(chunks)}")
            
            if chunks:
                print(f"   First chunk preview: {chunks[0].text[:100]}...")
            
            success_count += 1
            print("   ✅ Success\n")
            
        except Exception as e:
            print(f"   ❌ Failed: {e}\n")
    
    print(f"\n{'='*50}")
    print(f"Results: {success_count}/{len(pdf_files)} papers extracted successfully")
    
    return success_count > 0

if __name__ == "__main__":
    success = test_extraction()
    sys.exit(0 if success else 1)
