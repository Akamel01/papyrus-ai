
from src.utils.reference_splitter import split_references

def test_logic():
    # Scenario: 
    # 3 Papers Retrieved (A, B, C)
    # Text mentions A, B, and X (external)
    
    apa_refs = [
        "AuthorA, F. (2020). Title A.",
        "AuthorB, F. (2020). Title B.",
        "AuthorC, F. (2020). Title C."
    ]
    
    text = """
    This is a claim by AuthorA (2020).
    Another claim by AuthorB (2020).
    A third claim by AuthorX (2020) which is not retrieved.
    """
    
    cited, uncited = split_references(text, apa_refs)
    
    print(f"Retrieved Input: {len(apa_refs)}")
    print(f"Cited Output: {len(cited)}")
    print(f"Uncited Output: {len(uncited)}")
    
    # Check content
    print("\nCited:")
    for r in cited: print(r)
    
    print("\nUncited (Should be AuthorC):")
    for r in uncited: print(r)

    # Deducing the Gap
    # If user counts 3 citations (A, B, X)
    # And Cited = 2 (A, B)
    # Uncited = 1 (C)
    # Gap = 3 - 2 = 1.
    # Is C in the gap? No, C is reported as Uncited.
    # The Gap is X.
    
if __name__ == "__main__":
    test_logic()
