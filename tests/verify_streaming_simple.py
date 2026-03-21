
import sys
import os
import logging
import time
from pathlib import Path

# Add project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.storage import DatabaseManager, PaperStore
from src.acquisition.paper_discoverer import DiscoveredPaper
from src.pipeline.stages import DatabaseSource, DownloadStage, ChunkStage, BatcherStage, EmbedStage, StorageStage
from src.ingestion import create_chunker
from src.ingestion import create_chunker, create_parser
from src.acquisition.paper_downloader import PaperDownloader

# Mock objects
class MockEmbedder:
    def embed_batch(self, texts):
        return [[0.1] * 4096 for _ in texts] # Mock vectors

class MockVectorStore:
    def upsert(self, chunks):
        print(f"Upserted {len(chunks)} chunks to MockStore")

def verify_streaming():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("Test")
    
    # Setup DB
    db_path = "data/test_streaming.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    
    db_manager = DatabaseManager(db_path)
    paper_store = PaperStore(db_manager)
    
    # Insert Test Paper
    test_paper = DiscoveredPaper(
        doi="10.1234/test",
        title="Test Paper",
        pdf_url="https://arxiv.org/pdf/2301.12345.pdf", # Valid-looking URL
        status="discovered",
        source="test"
    )
    paper_store.add_paper(test_paper)
    logger.info(f"Inserted test paper into DB: {test_paper.unique_id}")
    
    # Setup Components
    downloader = PaperDownloader("data/test_papers", {"max_retries": 1})
    chunker = create_chunker(chunk_size=500, chunk_overlap=50)
    embedder = MockEmbedder()
    store = MockVectorStore()
    
    # Pipeline
    logger.info("Starting Pipeline...")
    source = DatabaseSource(paper_store)
    pipeline = source.stream()
    
    # We mock DownloadStage to simulate successful download w/o network
    # Actually, let's use real DownloadStage but mock the downloader?
    # Or just let it fail download and check error handling?
    # We want to verify flow. 
    # Let's mock a "downloaded" paper directly in DB to test the rest of the pipe?
    # Update paper to 'downloaded' and point to a dummy PDF.
    
    # Create dummy PDF
    dummy_pdf = Path("data/test_papers/dummy.pdf")
    dummy_pdf.parent.mkdir(parents=True, exist_ok=True)
    with open(dummy_pdf, "wb") as f:
        # Create a simple valid PDF with enough text
        # We simulate a PDF with a stream containing text
        import zlib
        
        content = b"""
        Title: Test Paper for Streaming
        Abstract: This is a test paper to verify the streaming pipeline. It must have enough characters to pass the quality threshold.
        Introduction:
        The quick brown fox jumps over the lazy dog. Repetition is key to length.
        The quick brown fox jumps over the lazy dog. Repetition is key to length.
        The quick brown fox jumps over the lazy dog. Repetition is key to length.
        The quick brown fox jumps over the lazy dog. Repetition is key to length.
        The quick brown fox jumps over the lazy dog. Repetition is key to length.
        The quick brown fox jumps over the lazy dog. Repetition is key to length.
        The quick brown fox jumps over the lazy dog. Repetition is key to length.
        This should be enough text to pass the 100 char limit and common word check.
        Values: the, and, of, to, in, a. (Ensure common words are present).
        """
        
        # Minimal PDF structure (approximate)
        # Using a valid pre-generated PDF or simple text extraction might be better.
        # But since parser uses pymupdf, we need a valid PDF structure.
        # Generating a valid PDF in pure python without library is hard.
        # Better: Copy an existing PDF from data? Or use reportlab if available?
        # Or just mocking the parser?
        # NO, we want to test interaction with parser.
        
        # Let's mock the parser.parse method in the script instead of fighting PDF format.
        pass
    
    # Mock Parser for this test to avoid binary PDF issues
    class MockParser:
        def parse(self, path):
             from src.core.interfaces import Document
             return Document(
                 doi="10.1234/test",
                 title="Test Paper",
                 abstract="Abstract...",
                 full_text="This is a test paper. " * 50,
                 metadata={}
             )
    
    parser = MockParser()
    # Update creation in pipeline flow

    
    # DownloadStage should passthrough
    pipeline = DownloadStage(downloader, paper_store).process(pipeline)
    pipeline = ChunkStage(parser.parse, chunker.chunk, paper_store).process(pipeline)
    pipeline = BatcherStage(batch_size=2, timeout=1.0).process(pipeline)
    pipeline = EmbedStage(embedder).process(pipeline)
    pipeline = StorageStage(store, paper_store).process(pipeline)
    
    count = 0
    for item in pipeline:
        if item.is_valid:
            print(f"Processed Batch: {len(item.payload)} chunks")
            count += 1
            
    if count > 0:
        logger.info("✅ Pipeline Success!")
        # Verify DB status
        p = paper_store.get_paper(test_paper.unique_id)
        if p.status == "embedded":
             logger.info("✅ DB Status Updated to 'embedded'")
        else:
             logger.error(f"❌ DB Status: {p.status}")
    else:
        logger.error("❌ Pipeline produced no output")

if __name__ == "__main__":
    verify_streaming()
