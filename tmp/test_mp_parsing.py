import os
import sys
from pathlib import Path
import logging
from concurrent.futures import ProcessPoolExecutor

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline.chunk_worker import process_paper_to_chunks

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_mp():
    # Correct path provided by user
    papers_dir = Path("C:/gpt/SME/DataBase/Papers")
    pdfs = list(papers_dir.glob("*.pdf"))
    
    if not pdfs:
        logger.error(f"No PDFs found in {papers_dir}")
        return

    test_pdf = pdfs[0]
    logger.info(f"Testing Multi-Process Parsing with: {test_pdf}")

    parser_cfg = {'quality_threshold': 0.7, 'use_markdown': False}
    chunker_cfg = {'chunk_size': 800, 'chunk_overlap': 150}
    
    metadata = {
        'doi': 'test/doi',
        'title': 'Test Paper',
        'authors': ['Author A'],
        'year': 2024,
        'apa_reference': 'Test Ref'
    }

    # Test the worker function directly in a separate process
    # (Matches what ConcurrentPipeline does)
    try:
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                process_paper_to_chunks,
                str(test_pdf),
                metadata,
                parser_cfg,
                chunker_cfg
            )
            chunks = future.result(timeout=30)
            
            logger.info("✅ SUCCESS!")
            logger.info(f"Generated {len(chunks)} chunks")
            if chunks:
                logger.info(f"First chunk preview: {chunks[0].text[:100]}...")
                logger.info(f"Metadata check: {chunks[0].metadata.get('apa_reference')}")

    except Exception as e:
        logger.error(f"❌ FAILED: {e}", exc_info=True)

if __name__ == "__main__":
    test_mp()
