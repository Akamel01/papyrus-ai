#!/usr/bin/env python
"""
Remediation Script for Failed PDF Ingestions.
Targets the ~3.5% of papers that failed due to Timeouts or Empty Content.

Strategy:
1. Load `data/failed_ingestion.jsonl`.
2. Classify failures:
   - "Timeout": Retry with standard PyMuPDF (faster/simpler than markdown parser).
   - "No content": Retry with OCR (if Tesseract available).
3. Upsert successful recoveries to Qdrant.
4. Update tracking.
"""

import json
import logging
import os
import sys
import uuid
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Optional, Dict, Any
from tqdm import tqdm
import threading

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion import create_chunker
from src.indexing import create_vector_store
from src.core import Document, Chunk
from src.utils.helpers import clean_text

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("remediation.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

FAILED_LOG = Path("data/failed_ingestion.jsonl")
REMEDIATED_LOG = Path("data/remediated.jsonl")

def load_failures() -> List[Dict]:
    """Load failed records."""
    if not FAILED_LOG.exists():
        return []
    
    failures = []
    with open(FAILED_LOG, 'r') as f:
        for line in f:
            if line.strip():
                failures.append(json.loads(line))
    return failures

def check_ocr_availability() -> bool:
    """Check if Tesseract is installed/configured."""
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False

def robust_parse(file_path: Path, use_ocr: bool = False) -> Optional[Document]:
    """
    Robust parsing strategy.
    1. Try standard fitz text extraction (fast & robust).
    2. If empty and use_ocr=True, try OCR.
    """
    try:
        doc = fitz.open(file_path)
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        
        text = clean_text(text)
        
        # If empty and OCR enabled, try OCR
        if not text and use_ocr:
            import pytesseract
            from pdf2image import convert_from_path
            
            logger.info(f"Running OCR on {file_path.name}...")
            images = convert_from_path(str(file_path))
            ocr_text = ""
            for img in images:
                ocr_text += pytesseract.image_to_string(img) + "\n"
            text = clean_text(ocr_text)

        if not text:
            return None

        # Create Document object
        # Note: We extract DOI from filename since we don't have metadata here easily
        from src.utils.helpers import extract_doi_from_filename
        doi = extract_doi_from_filename(file_path.name)
        
        return Document(
            doi=doi,
            title=file_path.stem, # Fallback title
            abstract="", # Missing abstract in fallback
            full_text=text,
            sections={}, 
            metadata={
                "extraction_method": "remediation_robust" if not use_ocr else "remediation_ocr",
                "file_path": str(file_path)
            },
            extraction_quality=0.5, # Penalize quality for fallback
            file_path=file_path
        )
        
    except Exception as e:
        logger.warning(f"Failed to parse {file_path.name}: {e}")
        return None

def main():
    failures = load_failures()
    logger.info(f"Loaded {len(failures)} failed records.")
    
    if not failures:
        logger.info("Nothing to remediate.")
        return

    # Check for OCR
    has_ocr = check_ocr_availability()
    if not has_ocr:
        logger.warning("Tesseract not found. 'No content' failures will likely fail again.")
    else:
        logger.info("OCR Engine (Tesseract) detected.")

    # Setup Vector Store
    from sentence_transformers import SentenceTransformer
    from qdrant_client.http import models as qmodels
    
    logger.info("Initializing GPU Model...")
    model = SentenceTransformer("BAAI/bge-large-en-v1.5", device="cuda")
    vector_store = create_vector_store()
    client = vector_store._get_client()
    collection_name = vector_store.collection_name
    chunker = create_chunker(chunk_size=800, chunk_overlap=150)

    # Track Processed
    processed = set()
    if REMEDIATED_LOG.exists():
        with open(REMEDIATED_LOG, 'r') as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    processed.add(rec['file'])

    to_process = [f for f in failures if f['file'] not in processed]
    logger.info(f"Processing {len(to_process)} remaining failures...")
    
    # Process Loop
    successful = 0
    
    for fail_rec in tqdm(to_process, desc="Remediating"):
        file_name = fail_rec['file']
        # Locate file (assuming structure DataBase/Papers)
        file_path = Path("DataBase/Papers") / file_name
        
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            continue

        # Strategy Selection
        is_timeout = "timeout" in fail_rec.get('error', '').lower()
        use_ocr_for_this = has_ocr and not is_timeout # Only OCR if it wasn't a timeout (timeouts have content, just slow)
        
        doc = robust_parse(file_path, use_ocr=use_ocr_for_this)
        
        if not doc or not doc.full_text:
            continue
            
        # Chunk
        chunks = chunker.chunk(doc)
        if not chunks:
            continue
            
        # Embed (Single Doc - slow but safe)
        try:
            texts = [c.text for c in chunks]
            embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            
            points = []
            for i, chunk in enumerate(chunks):
                if hasattr(embeddings[i], 'tolist'):
                     emb = embeddings[i].tolist()
                else:
                     emb = embeddings[i]
                     
                points.append(qmodels.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=emb,
                    payload=chunk.metadata
                ))
            
            # Upsert
            client.upsert(collection_name=collection_name, points=points)
            successful += 1
            
            # Log Success
            with open(REMEDIATED_LOG, 'a') as f:
                json.dump({"file": file_name, "status": "success", "chunks": len(points)}, f)
                f.write("\n")
                
        except Exception as e:
            logger.error(f"Failed to embed/upsert {file_name}: {e}")

    logger.info(f"Remediation Complete. Successfully recovered {successful}/{len(to_process)} papers.")

if __name__ == "__main__":
    main()
