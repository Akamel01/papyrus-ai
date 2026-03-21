import sys
from pathlib import Path

# Provide path directly since it's hard to resolve from tmp relative inside python
pdf_path = Path(r"C:\gpt\SME\DataBase\Papers\10.56082_annalsarscibio.2024.1.132.pdf")

print(f"Testing {pdf_path}")
if not pdf_path.exists():
    print("File not found.")
    sys.exit(1)

import fitz
print("PyMuPDF loaded.")
try:
    doc = fitz.open(pdf_path)
    print(f"Pages: {doc.page_count}")
    
    # Try basic text extraction first
    basic_text = ""
    for page in doc:
        basic_text += page.get_text()
    
    print(f"Basic text length: {len(basic_text)}")
    print(f"Basic text preview: {basic_text[:200]!r}")
    
    doc.close()
    
    # Try markdown extraction
    print("\nTrying pymupdf4llm...")
    import pymupdf4llm
    md_text = pymupdf4llm.to_markdown(pdf_path)
    print(f"MD text length: {len(md_text)}")
    print(f"MD text preview: {md_text[:200]!r}")

except Exception as e:
    print(f"Error during testing: {e}")
