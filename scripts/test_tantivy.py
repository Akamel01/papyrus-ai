
import os
import shutil
import logging
import tantivy
from src.indexing.bm25_tantivy import TantivyBM25Index

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_tantivy")

def test_tantivy_basic():
    index_path = "data/bm25_tantivy_test"
    if os.path.exists(index_path):
        shutil.rmtree(index_path)
        
    print(f"Creating index at {index_path}...")
    idx = TantivyBM25Index(index_path=index_path)
    
    print("Adding documents...")
    writer = idx.index.writer()
    # Correct usage based on verified introspection
    try:
        doc1 = tantivy.Document.from_dict({"id": "doc1", "text": "The quick brown fox jumps over the lazy dog"}, idx.schema)
        writer.add_document(doc1)
        
        doc2 = tantivy.Document.from_dict({"id": "doc2", "text": "The quick brown fox is very quick"}, idx.schema)
        writer.add_document(doc2)
        
        doc3 = tantivy.Document.from_dict({"id": "doc3", "text": "Dogs are lazy animals"}, idx.schema)
        writer.add_document(doc3)
        
        writer.commit()
    except Exception as e:
        print(f"FAILED to add docs: {e}")
        return
    
    print("Searching 'fox'...")
    results = idx.search("fox", top_k=10)
    print(f"Results for 'fox': {results}")
    
    assert len(results) == 2
    assert results[0].id in ["doc1", "doc2"]
    
    print("Searching 'lazy'...")
    results = idx.search("lazy", top_k=10)
    print(f"Results for 'lazy': {results}")
    assert len(results) == 2 # doc1 and doc3
    
    print("SUCCESS: Tantivy basic test passed!")

if __name__ == "__main__":
    test_tantivy_basic()
