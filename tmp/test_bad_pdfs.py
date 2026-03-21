import sys
import fitz
from pathlib import Path

bad_pdfs = [
    r"/app/DataBase/Papers/10.26719_2003.9.3.448.pdf",
    r"/app/DataBase/Papers/10.17816_kazmj84082.pdf",
    r"/app/DataBase/Papers/10.17816_nb81043.pdf",
    r"/app/DataBase/Papers/10.31222_osf.io_ceda3.pdf"
]

def analyze_pdf(path_str):
    path = Path(path_str)
    print(f"\n{'='*60}")
    print(f"Analyzing: {path.name}")
    
    if not path.exists():
        print("  -> ERROR: File does not exist on disk!")
        return
        
    print(f"  Size: {path.stat().st_size / 1024:.2f} KB")
        
    try:
        doc = fitz.open(path)
        print(f"  Pages: {doc.page_count}")
        print(f"  Requires Password: {doc.needs_pass}")
        print(f"  Is Encrypted: {doc.is_encrypted}")
        
        # Test basic extraction length
        basic_text = ""
        for page in doc:
            basic_text += page.get_text()
            
        print(f"  Raw Extracted Char Count: {len(basic_text)}")
        
        # Sample the raw text
        sample = basic_text[:200].replace('\n', ' ')
        print(f"  Raw Text Sample: {sample!r}")
        
        doc.close()
    except Exception as e:
        print(f"  -> ERROR during PyMuPDF parsing: {e}")

if __name__ == "__main__":
    for pdf in bad_pdfs:
        analyze_pdf(pdf)
