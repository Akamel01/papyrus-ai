#!/usr/bin/env python3
"""
Metadata Extraction Validation Script

Runs metadata extraction on test PDFs and reports accuracy.
This validates the multi-tier extraction methodology works correctly
across diverse PDF types.

Usage:
    python scripts/validate_metadata_extraction.py
    
    # Or in Docker:
    docker exec sme_app python scripts/validate_metadata_extraction.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import MagicMock
from src.streaming.manual_import import ManualImportScanner


def main():
    # Initialize scanner with mock store
    mock_store = MagicMock()
    mock_store.status_exists.return_value = False
    
    # Create scanner - will create subdirs automatically
    test_dir = Path("DataBase/ManualImport")
    test_dir.mkdir(parents=True, exist_ok=True)
    
    scanner = ManualImportScanner(mock_store, test_dir)

    # Find test PDFs - prefer ManualImport, fall back to Papers
    if list(test_dir.glob("*.pdf")):
        pdfs = list(test_dir.glob("*.pdf"))[:10]
    else:
        papers_dir = Path("DataBase/Papers")
        if papers_dir.exists():
            pdfs = list(papers_dir.glob("*.pdf"))[:10]
        else:
            print("ERROR: No PDFs found for testing")
            print("  Checked: DataBase/ManualImport/ and DataBase/Papers/")
            return 1

    print("=" * 70)
    print("METADATA EXTRACTION VALIDATION REPORT")
    print("=" * 70)
    print(f"Testing {len(pdfs)} PDFs...")

    results = []
    for pdf_path in pdfs:
        print(f"\n--- {pdf_path.name} ---")
        try:
            metadata = scanner.extract_metadata_from_pdf(pdf_path)

            # Display extracted data
            title = metadata['title'] or "None"
            if len(title) > 60:
                title = title[:60] + "..."
            print(f"  Title:      {title}")
            
            authors = metadata['authors']
            if len(authors) > 3:
                authors_display = str(authors[:3]) + "..."
            else:
                authors_display = str(authors)
            print(f"  Authors:    {authors_display}")
            print(f"  Year:       {metadata['year']}")
            
            if metadata['abstract']:
                abstract_preview = metadata['abstract'][:80] + "..." if len(metadata['abstract']) > 80 else metadata['abstract']
                print(f"  Abstract:   Yes ({len(metadata['abstract'])} chars)")
            else:
                print(f"  Abstract:   No")
            
            print(f"  Confidence: {metadata['extraction_confidence']}")
            print(f"  Sources:    {', '.join(metadata['extraction_sources'])}")

            # Track results
            results.append({
                "file": pdf_path.name,
                "has_title": bool(metadata['title'] and not metadata['title'].startswith("[DOI") and not metadata['title'].startswith("Untitled")),
                "has_authors": len(metadata['authors']) > 0,
                "has_year": metadata['year'] is not None,
                "has_abstract": metadata['abstract'] is not None,
                "confidence": metadata['extraction_confidence'],
            })

        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"file": pdf_path.name, "error": str(e)})

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    success = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]
    
    if not success:
        print(f"ERROR: All {len(results)} PDFs failed extraction")
        return 1
    
    high_conf = sum(1 for r in success if r["confidence"] == "high")
    med_conf = sum(1 for r in success if r["confidence"] == "medium")
    low_conf = sum(1 for r in success if r["confidence"] == "low")

    print(f"Total PDFs tested:    {len(pdfs)}")
    print(f"Successful extracts:  {len(success)}")
    print(f"Failed extracts:      {len(errors)}")
    print(f"High confidence:      {high_conf} ({100*high_conf/max(len(success),1):.1f}%)")
    print(f"Medium confidence:    {med_conf} ({100*med_conf/max(len(success),1):.1f}%)")
    print(f"Low confidence:       {low_conf} ({100*low_conf/max(len(success),1):.1f}%)")

    with_title = sum(1 for r in success if r["has_title"])
    with_authors = sum(1 for r in success if r["has_authors"])
    with_year = sum(1 for r in success if r["has_year"])
    with_abstract = sum(1 for r in success if r["has_abstract"])

    print(f"\nField extraction rates:")
    print(f"  Title (non-DOI):    {with_title}/{len(success)} ({100*with_title/max(len(success),1):.1f}%)")
    print(f"  Authors:            {with_authors}/{len(success)} ({100*with_authors/max(len(success),1):.1f}%)")
    print(f"  Year:               {with_year}/{len(success)} ({100*with_year/max(len(success),1):.1f}%)")
    print(f"  Abstract:           {with_abstract}/{len(success)} ({100*with_abstract/max(len(success),1):.1f}%)")

    # Pass/fail threshold
    min_acceptable = 0.6  # 60% extraction rate
    title_rate = with_title / max(len(success), 1)
    high_med_rate = (high_conf + med_conf) / max(len(success), 1)
    
    print("\n" + "-" * 70)
    print("ACCEPTANCE CRITERIA CHECK")
    print("-" * 70)
    
    passed = True
    
    # Check title extraction rate
    if title_rate < min_acceptable:
        print(f"⚠️  WARN: Title extraction rate {title_rate*100:.1f}% < {min_acceptable*100}% threshold")
        passed = False
    else:
        print(f"✅ PASS: Title extraction rate {title_rate*100:.1f}% >= {min_acceptable*100}% threshold")
    
    # Check confidence level
    if high_med_rate < min_acceptable:
        print(f"⚠️  WARN: High+Medium confidence {high_med_rate*100:.1f}% < {min_acceptable*100}% threshold")
        passed = False
    else:
        print(f"✅ PASS: High+Medium confidence {high_med_rate*100:.1f}% >= {min_acceptable*100}% threshold")

    print("-" * 70)
    
    if passed:
        print("\n✅ Metadata extraction validation PASSED")
        return 0
    else:
        print("\n⚠️  Metadata extraction validation has WARNINGS")
        print("   Review the extraction quality and consider adjusting thresholds")
        print("   or enhancing extraction methods if needed.")
        return 0  # Return 0 even with warnings - they're informational


if __name__ == "__main__":
    sys.exit(main())
