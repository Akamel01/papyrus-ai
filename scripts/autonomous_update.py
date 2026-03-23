"""
SME Autonomous Update Pipeline — Gold Standard

Orchestrates the full streaming ingestion pipeline:
  Discovery → Download → Chunk → Embed → Store

Features:
  - Auto-Tuner: hardware probe + HNSW parameter validation at startup
  - PipelineMonitor: heartbeat, throughput metrics, GPU tracking, alerts
  - Startup PDF Cleanup: removes orphaned PDFs from previous runs
  - Inline PDF Deletion: deletes PDFs immediately after successful storage
  - Graceful Shutdown: SIGTERM handler bridges to both source and pipeline
"""

import logging
import argparse
import signal
import sys
import os
import uuid
import time
from pathlib import Path
from threading import Event, Thread

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.helpers import load_config
from src.storage.db import DatabaseManager
from src.storage.paper_store import PaperStore
from src.acquisition.paper_downloader import PaperDownloader
from src.acquisition.paper_discoverer import PaperDiscoverer
from src.indexing.embedder import create_embedder
from src.indexing.vector_store import create_vector_store
from src.indexing.qdrant_optimizer import run_startup_optimization
from src.indexing.bm25_index import create_bm25_index
from src.pipeline.stages import DatabaseSource, DownloadStage, ChunkStage, EmbedStage, StorageStage
from src.pipeline.concurrent_pipeline import ConcurrentPipeline
from src.pipeline.dead_letter_queue import DeadLetterQueue
from src.pipeline.monitor import PipelineMonitor, PipelinePhase, PipelineStatus
from src.ingestion.pdf_parser import PyMuPDFParser
from src.ingestion.chunker import HierarchicalChunker
from src.pipeline.gpu_tuner import startup_gpu_report, derive_startup_config
from src.core.exceptions import LowQualityExtractionError, InvalidPDFError
from src.pipeline.retry_policy import RetryPolicy
from src.streaming.manual_import import ManualImportScanner, move_to_embedded, move_to_failed_parse

# Configure logging
os.makedirs("data", exist_ok=True)
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Clear existing handlers to prevent duplicates if basicConfig was called
if root_logger.hasHandlers():
    root_logger.handlers.clear()

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Stream Handler
stream_out = logging.StreamHandler(sys.stdout)
stream_out.setFormatter(formatter)
root_logger.addHandler(stream_out)

# File Handler
file_out = logging.FileHandler("data/autonomous_update.log")
file_out.setFormatter(formatter)
root_logger.addHandler(file_out)

logger = logging.getLogger("autonomous_update")


# ──────────────────────────────────────────────────────────────────────────────
# Startup Maintenance
# ──────────────────────────────────────────────────────────────────────────────

def _cleanup_embedded_pdfs(paper_store: PaperStore, papers_dir: Path):
    """
    Remove PDF files for papers already marked 'embedded' in the database.
    Prevents disk waste from previous runs that completed embedding but
    didn't clean up their source files.
    """
    if not papers_dir.exists():
        logger.info(f"[CLEANUP] Papers dir does not exist: {papers_dir}")
        return

    cleaned = 0
    errors = 0
    for pdf_file in papers_dir.glob("*.pdf"):
        try:
            raw = pdf_file.stem
            # Convert filename to unique_id format used in DB
            if raw.startswith("10."):
                parts = raw.split("_", 1)
                uid = f"doi:{parts[0]}/{parts[1]}".lower() if len(parts) == 2 else raw
            elif raw.startswith("arXiv-"):
                uid = f"arxiv:{raw.replace('arXiv-', '')}".lower()
            else:
                uid = raw  # Fallback: use as-is
            paper = paper_store.get_paper(uid)
            if paper and paper.status == "embedded":
                pdf_file.unlink(missing_ok=True)
                cleaned += 1
        except Exception as e:
            errors += 1
            logger.debug(f"[CLEANUP] Error checking {pdf_file.name}: {e}")

    logger.info(f"[CLEANUP] Startup sweep: removed {cleaned} orphaned PDFs, {errors} errors")


def _discovery_worker(discoverer: PaperDiscoverer, paper_store: PaperStore, config: dict, stop_event: Event):
    """
    Background daemon thread that continuously discovers papers and writes them to the database in batches.
    Utilizes PaperStore.add_papers_batch() to minimize SQLite WAL write-locks.
    """
    acq_config = config.get('acquisition', {})
    keywords = acq_config.get('keywords', [])
    filters = acq_config.get('filters', {})
    batch_size = filters.get('discovery_batch_size', 100)
    
    logger.info("=" * 60)
    logger.info("[DISCOVERY-WORKER] Initializing Search Parameters:")
    logger.info(f"  - Keywords ({len(keywords)}): {keywords}")
    logger.info(f"  - Year Filter: {filters.get('year', 'Any')}")
    logger.info(f"  - From Updated Date: {filters.get('from_updated_date', 'Any')}")
    logger.info(f"  - Publication Types: {filters.get('publication_types', 'Any')}")
    logger.info(f"  - Batch Size: {batch_size}")
    logger.info("=" * 60)
    
    try:
        current_batch = []
        # Using discover_stream which yields papers efficiently
        for paper in discoverer.discover_stream(keywords=keywords, filters=filters, exclude_existing=True):
            if stop_event.is_set():
                logger.info("[DISCOVERY-WORKER] Stop signal received, halting discovery.")
                break
                
            current_batch.append(paper)
            logger.debug(f"[DISCOVERY-WORKER] Queued: {paper.title} ({paper.year}) [{paper.source}]")
            
            if len(current_batch) >= batch_size:
                added = paper_store.add_papers_batch(current_batch)
                logger.info(f"[DISCOVERY-WORKER] Flushed batch of {len(current_batch)} to DB. (Successfully wrote: {added} new)")
                
                # Log metadata of newly written papers (approximate from batch)
                if added > 0:
                    for p in current_batch[:added]:
                        authors = p.authors[:2] + ["..."] if len(p.authors) > 2 else p.authors
                        logger.info(f"  -> [NEW DATA] {p.unique_id} | Year: {p.year} | Source: {p.source} | Authors: {authors}")
                        
                current_batch = []
                
        # Flush remaining
        if current_batch and not stop_event.is_set():
            added = paper_store.add_papers_batch(current_batch)
            logger.info(f"[DISCOVERY-WORKER] Flushed final batch of {len(current_batch)} to DB. (Successfully wrote: {added} new)")
            if added > 0:
                for p in current_batch[:added]:
                    authors = p.authors[:2] + ["..."] if len(p.authors) > 2 else p.authors
                    logger.info(f"  -> [NEW DATA] {p.unique_id} | Year: {p.year} | Source: {p.source} | Authors: {authors}")
            
    except Exception as e:
        logger.error(f"[DISCOVERY-WORKER] Fatal error: {e}", exc_info=True)
    finally:
        logger.info("[DISCOVERY-WORKER] Stopped.")

# ──────────────────────────────────────────────────────────────────────────────
# BM25 Startup Resume
# ──────────────────────────────────────────────────────────────────────────────

def _resume_bm25_indexing(paper_store: PaperStore, bm25_index, vector_store) -> int:
    """
    Index papers that are embedded but not yet BM25 indexed.

    This handles the gap when the pipeline stops with papers embedded in Qdrant
    but not yet indexed in Tantivy. Called at startup before the pipeline runs.

    Args:
        paper_store: PaperStore instance
        bm25_index: TantivyBM25Index instance
        vector_store: QdrantVectorStore instance (for fetching chunk texts)

    Returns:
        Number of papers indexed
    """
    import tantivy
    from qdrant_client import models

    total_indexed = 0
    batch_size = 500

    while True:
        # Get papers that are embedded but not BM25 indexed
        unindexed = paper_store.get_unindexed_bm25_papers(limit=batch_size)
        if not unindexed:
            break

        logger.info(f"[BM25-RESUME] Found {len(unindexed)} unindexed papers, processing...")

        # Get Qdrant client
        try:
            client = vector_store._get_client()
            collection = vector_store.collection_name
        except Exception as e:
            logger.error(f"[BM25-RESUME] Failed to get Qdrant client: {e}")
            break

        # Create Tantivy writer (wrapped in try/finally to ensure cleanup)
        writer = None
        try:
            writer = bm25_index.tantivy_index.writer(heap_size=64 * 1024 * 1024)
        except Exception as e:
            logger.error(f"[BM25-RESUME] Failed to create writer: {e}")
            break

        indexed_in_batch = 0
        papers_to_mark = []

        for paper_id in unindexed:
            try:
                # Scroll Qdrant for chunks belonging to this paper
                # Extract DOI value from unique_id (e.g., "doi:10.1234/xyz" -> "10.1234/xyz")
                doi_value = paper_id
                if paper_id.startswith("doi:"):
                    doi_value = paper_id[4:]
                elif paper_id.startswith("arxiv:"):
                    doi_value = paper_id[6:]

                chunks_found = 0
                offset = None

                while True:
                    results, next_offset = client.scroll(
                        collection_name=collection,
                        limit=100,
                        offset=offset,
                        scroll_filter=models.Filter(
                            must=[models.FieldCondition(
                                key="doi",
                                match=models.MatchValue(value=doi_value)
                            )]
                        ),
                        with_payload=True,
                        with_vectors=False,
                    )

                    if not results:
                        break

                    for point in results:
                        payload = point.payload or {}
                        text = payload.get("text", "")
                        if text.strip():
                            doc_dict = {"id": str(point.id), "text": text}
                            writer.add_document(
                                tantivy.Document.from_dict(doc_dict, bm25_index.schema)
                            )
                            chunks_found += 1

                    if next_offset is None:
                        break
                    offset = next_offset

                if chunks_found > 0:
                    papers_to_mark.append(paper_id)
                    indexed_in_batch += chunks_found

            except Exception as e:
                logger.warning(f"[BM25-RESUME] Failed to index paper {paper_id}: {e}")

        # Commit batch and release writer
        try:
            if papers_to_mark:
                writer.commit()
                marked = paper_store.mark_bm25_indexed(papers_to_mark)
                total_indexed += len(papers_to_mark)
                logger.info(
                    f"[BM25-RESUME] Batch complete: {len(papers_to_mark)} papers, "
                    f"{indexed_in_batch} chunks, marked={marked}"
                )
            else:
                # No papers found in this batch (maybe filter didn't match)
                # Mark them anyway to prevent infinite loop
                paper_store.mark_bm25_indexed(unindexed)
                logger.warning(f"[BM25-RESUME] No chunks found for {len(unindexed)} papers, marking as indexed")
        finally:
            # Explicitly release the writer and reload index to release lock
            del writer
            import gc
            gc.collect()
            bm25_index.tantivy_index.reload()

    if total_indexed > 0:
        logger.info(f"[BM25-RESUME] ✅ Resume complete: indexed {total_indexed} papers")
    else:
        logger.info("[BM25-RESUME] No papers needed indexing")

    return total_indexed


def _resume_bm25_async(
    paper_store: PaperStore,
    bm25_queue,
    vector_store,
    stop_event: Event
) -> None:
    """
    Background thread that resumes BM25 indexing without blocking the pipeline.

    Instead of holding a Tantivy writer and blocking, this function:
    1. Fetches unindexed papers in batches from SQLite
    2. Retrieves chunk texts from Qdrant
    3. Queues BM25IndexItem objects to the same queue that BM25Worker consumes

    This allows the pipeline to start immediately while resume runs in parallel.
    The BM25Worker handles both resume items AND live pipeline items concurrently.

    Args:
        paper_store: PaperStore instance
        bm25_queue: Queue that BM25Worker consumes from
        vector_store: QdrantVectorStore for fetching chunk texts
        stop_event: Event to signal early termination
    """
    from qdrant_client import models
    from src.pipeline.bm25_worker import BM25IndexItem

    batch_size = 100  # Smaller batches for smoother interleaving with live items
    total_queued = 0

    logger.info("[BM25-RESUME-ASYNC] Starting background resume thread")

    try:
        # Get Qdrant client once
        try:
            client = vector_store._get_client()
            collection = vector_store.collection_name
        except Exception as e:
            logger.error(f"[BM25-RESUME-ASYNC] Failed to get Qdrant client: {e}")
            return

        while not stop_event.is_set():
            # Get next batch of unindexed papers
            unindexed = paper_store.get_unindexed_bm25_papers(limit=batch_size)
            if not unindexed:
                logger.info(f"[BM25-RESUME-ASYNC] Complete - queued {total_queued} papers for indexing")
                break

            logger.info(f"[BM25-RESUME-ASYNC] Processing batch of {len(unindexed)} papers...")

            for paper_id in unindexed:
                if stop_event.is_set():
                    logger.info("[BM25-RESUME-ASYNC] Stop signal received, exiting")
                    return

                try:
                    # Extract DOI value from unique_id
                    doi_value = paper_id
                    if paper_id.startswith("doi:"):
                        doi_value = paper_id[4:]
                    elif paper_id.startswith("arxiv:"):
                        doi_value = paper_id[6:]

                    # Fetch chunks from Qdrant
                    chunk_ids = []
                    texts = []
                    offset = None

                    while True:
                        results, next_offset = client.scroll(
                            collection_name=collection,
                            limit=100,
                            offset=offset,
                            scroll_filter=models.Filter(
                                must=[models.FieldCondition(
                                    key="doi",
                                    match=models.MatchValue(value=doi_value)
                                )]
                            ),
                            with_payload=True,
                            with_vectors=False,
                        )

                        if not results:
                            break

                        for point in results:
                            payload = point.payload or {}
                            text = payload.get("text", "")
                            if text.strip():
                                chunk_ids.append(str(point.id))
                                texts.append(text)

                        if next_offset is None:
                            break
                        offset = next_offset

                    if chunk_ids:
                        # Create BM25IndexItem and queue it
                        bm25_item = BM25IndexItem(
                            paper_unique_id=paper_id,
                            chunk_ids=chunk_ids,
                            texts=texts
                        )

                        # Queue with backpressure - if queue is full, wait briefly
                        while not stop_event.is_set():
                            try:
                                bm25_queue.put(bm25_item, timeout=2.0)
                                total_queued += 1
                                break
                            except Exception:
                                # Queue full, wait and retry
                                logger.debug("[BM25-RESUME-ASYNC] Queue full, waiting...")
                                continue
                    else:
                        # No chunks found - mark as indexed to prevent infinite loop
                        paper_store.mark_bm25_indexed([paper_id])
                        logger.warning(f"[BM25-RESUME-ASYNC] No chunks found for {paper_id}, marked as indexed")

                except Exception as e:
                    logger.warning(f"[BM25-RESUME-ASYNC] Failed to process {paper_id}: {e}")

            # Small delay between batches to avoid overwhelming the queue
            time.sleep(0.1)

    except Exception as e:
        logger.error(f"[BM25-RESUME-ASYNC] Fatal error: {e}", exc_info=True)
    finally:
        logger.info(f"[BM25-RESUME-ASYNC] Thread stopped | queued={total_queued}")


# ──────────────────────────────────────────────────────────────────────────────
# Manual Import Handler
# ──────────────────────────────────────────────────────────────────────────────

def run_manual_import(paper_store: PaperStore, config: dict) -> int:
    """
    Scan ManualImport directory and register PDFs for processing.

    Returns:
        Number of PDFs successfully registered
    """
    import_dir = Path(config.get('system', {}).get('manual_import_dir', 'DataBase/ManualImport'))

    logger.info("=" * 60)
    logger.info("[MANUAL-IMPORT] Starting Manual Import Scan")
    logger.info(f"  Directory: {import_dir}")
    logger.info("=" * 60)

    scanner = ManualImportScanner(
        paper_store=paper_store,
        import_dir=import_dir
    )

    results = scanner.scan_and_register()

    success_count = sum(1 for r in results if r.success)
    skip_count = sum(1 for r in results if not r.success)

    logger.info("=" * 60)
    logger.info("[MANUAL-IMPORT] Scan Complete")
    logger.info(f"  Total PDFs found: {len(results)}")
    logger.info(f"  Successfully registered: {success_count}")
    logger.info(f"  Skipped (duplicates/errors): {skip_count}")
    logger.info("=" * 60)

    return success_count


def cleanup_failed_manual_imports(paper_store: PaperStore, manual_import_dir: Path):
    """
    Scan database for manual imports that failed pipeline processing and move
    their corresponding PDFs from ManualImport to failed_parse directory.
    """
    logger.info("=" * 60)
    logger.info("[MANUAL-IMPORT] Sweeping failed imports...")
    
    failed_dir = manual_import_dir / "failed_parse"
    from src.streaming.manual_import import move_to_failed_parse
    
    query = '''
    SELECT unique_id, pdf_path FROM papers 
    WHERE source = 'manual_import' 
    AND status IN ('failed_parse', 'dlq_chunk', 'dlq_embed', 'dlq_store')
    '''
    
    moved_count = 0
    with paper_store.db.get_connection() as conn:
        for uid, p_path in conn.execute(query).fetchall():
            if p_path and Path(p_path).exists():
                # Prevent moving files that are already mapped to failed_parse folder somehow
                if "failed_parse" not in str(p_path):
                    logger.info(f"  -> Isolating failed paper: {uid}")
                    if move_to_failed_parse(Path(p_path), failed_dir):
                        moved_count += 1
                    
    logger.info(f"[MANUAL-IMPORT] Moved {moved_count} failed PDFs to isolation.")
    logger.info("=" * 60)


def check_manual_import_completion(manual_import_dir: Path) -> bool:
    """
    Check if manual import is complete (no PDFs in root directory).
    Returns True if complete, False if PDFs remain.
    """
    pdf_files = list(manual_import_dir.glob("*.pdf"))
    if pdf_files:
        logger.info(f"[MANUAL-IMPORT] {len(pdf_files)} PDFs still in directory")
        return False
    logger.info(f"[MANUAL-IMPORT] Directory clear - all PDFs processed")
    return True


def create_manual_import_success_callback(base_callback, manual_import_dir: Path, monitor):
    """
    Wrap the standard success callback to also move manual import PDFs.
    
    For manual imports, moves PDFs to embedded/ subdirectory after successful storage.
    For API-downloaded PDFs, delegates to the base callback which deletes them.
    
    Args:
        base_callback: Original success callback (updates metrics + deletes PDF)
        manual_import_dir: Path to ManualImport directory
        monitor: PipelineMonitor instance for metrics
    """
    embedded_dir = manual_import_dir / "embedded"

    def wrapped_callback(paper, chunk_count):
        if paper.pdf_path and "ManualImport" in str(paper.pdf_path):
            # For manual imports: update metrics, then move file (don't delete)
            monitor.increment("embedding", "pdfs_processed")
            monitor.increment("embedding", "chunks_embedded", chunk_count)
            monitor.heartbeat()
            move_to_embedded(paper.pdf_path, embedded_dir)
        else:
            # For API downloads: use original callback (updates metrics + deletes PDF)
            base_callback(paper, chunk_count)

    return wrapped_callback


# ──────────────────────────────────────────────────────────────────────────────
# Main Pipeline
# ──────────────────────────────────────────────────────────────────────────────

def run_pipeline(args):
    config_path = args.config or "config/config.yaml"
    config = load_config(config_path)

    # ── Initialize Core Components ──
    logger.info("=" * 72)
    logger.info("SME Autonomous Update Pipeline — Starting")
    logger.info("=" * 72)

    # Path handling for database
    db_path = config.get('chat', {}).get('history_db', 'data/sme.db').replace('chat_history.db', 'sme.db')
    if not os.path.exists(os.path.dirname(db_path)) and os.path.dirname(db_path):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    db_manager = DatabaseManager(db_path=db_path)
    paper_store = PaperStore(db_manager=db_manager)

    # PaperDownloader initialization with individual args
    acq_config = config.get('acquisition', {})
    papers_dir = Path(config.get('system', {}).get('papers_dir', './DataBase/Papers'))
    manual_import_dir = Path(config.get('system', {}).get('manual_import_dir', 'DataBase/ManualImport'))
    downloader = PaperDownloader(
        output_dir=papers_dir,
        email=acq_config.get('email'),
        openalex_api_key=acq_config.get('openalex_api_key'),
        max_retries=acq_config.get('max_retries', 3),
        timeout=acq_config.get('timeout', 120),
        requests_per_minute=acq_config.get('requests_per_minute', 30)
    )

    discoverer = PaperDiscoverer(
        emails=[acq_config.get('email')] if acq_config.get('email') else None,
        semantic_scholar_api_key=acq_config.get('semantic_scholar_api_key'),
        enable_openalex=acq_config.get('enable_openalex', True),
        enable_semantic_scholar=acq_config.get('enable_semantic_scholar', False),
        enable_arxiv=acq_config.get('enable_arxiv', True),
        enable_crossref=acq_config.get('enable_crossref', False),
        papers_dir=papers_dir
    )

    # ── Startup PDF Cleanup ──
    logger.info("[STARTUP] Running orphaned PDF cleanup...")
    _cleanup_embedded_pdfs(paper_store, papers_dir)

    # ── Startup Status Recovery ──
    # Reset any 'chunked' papers back to 'downloaded' to handle previous run interruptions.
    logger.info("[STARTUP] Checking for interrupted 'chunked' papers...")
    recovered_count = paper_store.reset_transient_status('chunked', 'downloaded')
    if recovered_count > 0:
        logger.info(f"[STARTUP] Recovered {recovered_count} 'chunked' papers for re-processing.")

    # ── Load Model-Heavy Components ──
    # ── Auto-Tuner (ONE call only) ──
    collection_name = acq_config.get('collection_name', 'sme_papers_v2')
    try:
        tuning_result = run_startup_optimization(
            client=None, # It will initialize its own temporary client to check index
            collection_name=collection_name,
            config=config,
            skip_index_gate=args.test  # Skip gate in test mode for faster startup
        )
        if tuning_result.get("status") == "FAILED":
            logger.error(f"[AUTO-TUNER] Non-fatal: optimization failed: {tuning_result.get('error')}")
            auto_config = derive_startup_config() # Fallback to CPU-only defaults
        else:
            config["optimized_params"] = tuning_result.get("optimal_params")
            # Derive specific pipeline worker/queue counts from the probe results
            gpu_info = tuning_result.get("hardware", {})
            auto_config = derive_startup_config(gpu_info=gpu_info)
            
            logger.info(
                f"[AUTO-TUNER] Tier={tuning_result.get('tier')}, "
                f"index_ready={tuning_result.get('index_ready')}"
            )
            # Merge auto_config into our main config
            config["auto_config"] = auto_config
    except Exception as e:
        logger.warning(f"[AUTO-TUNER] Non-fatal: optimization failed: {e}")
        logger.warning("[AUTO-TUNER] Pipeline will continue with current Qdrant configuration")

    # ── Initialize Auto-params for Stage Configuration ──
    auto_params = config.get("auto_config", {})

    # ── Embedder (direct init — no reranker/LLM/BM25) ──
    embedder_config = config.get('embedding', {})
    remote_url = embedder_config.get('remote_url')

    try:
        embedder = create_embedder(
            model_name=embedder_config.get('model_name', 'Qwen/Qwen3-Embedding-8B'),
            device=embedder_config.get('device', 'cuda'),
            batch_size=embedder_config.get('batch_size', 32),
            quantization=embedder_config.get('quantization', '4bit'),
            max_seq_length=embedder_config.get('max_seq_length', 4096),
            remote_url=remote_url,
            enable_fallback=False  # We'll handle fallback ourselves
        )
        embedder.load()  # auto-tunes batch size + starts GPUHealthMonitor

    except Exception as e:
        if remote_url:
            logger.error(f"RemoteEmbedder failed to load: {e}")
            logger.warning("Falling back to local TransformerEmbedder (will download ~14GB model)")
            # Recreate without remote_url to force local embedder
            embedder = create_embedder(
                model_name=embedder_config.get('model_name', 'Qwen/Qwen3-Embedding-8B'),
                device=embedder_config.get('device', 'cuda'),
                batch_size=embedder_config.get('batch_size', 32),
                quantization=embedder_config.get('quantization', '4bit'),
                max_seq_length=embedder_config.get('max_seq_length', 4096),
                remote_url=None  # Force local embedder
            )
            embedder.load()
        else:
            # No remote URL, so this was a local embedder failure - re-raise
            raise

    # ── Vector Store ──
    vector_config = config.get('vector_store', {})
    vector_store = create_vector_store(
        host=vector_config.get('host', 'localhost'),
        port=vector_config.get('port', 6333),
        collection_name=vector_config.get('collection_name', 'sme_papers_v2'),
        embedding_dimension=embedder_config.get('dimension', 4096),
        timeout=vector_config.get('timeout', 10),
        optimized_params=config.get('optimized_params')
    )

    # ── BM25 Tantivy Index (for concurrent indexing) ──
    bm25_config = config.get('bm25', {})
    bm25_enabled = bm25_config.get('enabled', True) and bm25_config.get('use_tantivy', True)
    bm25_index = None

    if bm25_enabled:
        try:
            bm25_index = create_bm25_index(
                index_path=bm25_config.get('index_path', 'data/bm25_index.tantivy'),
                use_tantivy=True,
                vector_store=vector_store
            )
            logger.info("[STARTUP] BM25 Tantivy index loaded for concurrent indexing")

            # Check for unindexed papers (will be resumed in background after pipeline starts)
            unindexed_count = len(paper_store.get_unindexed_bm25_papers(limit=1))
            if unindexed_count > 0:
                logger.info("[STARTUP] BM25 resume will run in background (non-blocking)")
            else:
                logger.info("[STARTUP] No BM25 resume needed")

        except Exception as e:
            logger.warning(f"[STARTUP] Failed to initialize BM25 index: {e}")
            logger.warning("[STARTUP] Pipeline will run without concurrent BM25 indexing")
            bm25_index = None

    # ── Initialize DLQ ──
    dlq = DeadLetterQueue(db_path=db_path)

    # ── Initialize Ingestion Components ──
    ingest_config = config.get('ingestion', {})
    chunk_config = config.get('chunking', {})

    parser = PyMuPDFParser(
        quality_threshold=ingest_config.get('quality_threshold', 0.7),
        use_markdown=(ingest_config.get('pdf_parser') == "pymupdf4llm")
    )

    chunker = HierarchicalChunker(
        chunk_size=chunk_config.get('chunk_size', 800),
        chunk_overlap=chunk_config.get('chunk_overlap', 150),
        min_chunk_size=chunk_config.get('min_chunk_size', 100),
        tokenizer_name=chunk_config.get('tokenizer', "cl100k_base")
    )

    # ── Pipeline Monitor ──
    data_dir = Path(config.get('system', {}).get('data_dir', 'data'))
    monitor = PipelineMonitor(
        run_id=str(uuid.uuid4()),
        metrics_file=data_dir / 'pipeline_metrics.json',
        papers_dir=papers_dir,
        heartbeat_interval=10
    )

    # ── Graceful Shutdown ──
    stop_event = Event()

    # ── Define Stages ──
    is_manual = getattr(args, 'manual', False)
    target_status = 'downloaded' if (args.embed_only or is_manual) else 'discovered'
    
    source = DatabaseSource(
        paper_store=paper_store,
        batch_size=args.batch_size,
        continuous=(args.stream and not is_manual), # Override continuous mode if manual
        target_status=target_status,
        path_filter=str(manual_import_dir) if is_manual else None,  # NEW: filter by directory path
        stop_signal=stop_event
    )

    download_stage = DownloadStage(
        downloader=downloader,
        paper_store=paper_store,
        max_workers=auto_params.get('download_workers', acq_config.get('max_concurrent_downloads', 4))
    )

    chunk_stage = ChunkStage(
        parser_func=parser.parse,
        chunker_func=chunker.chunk,
        paper_store=paper_store
    )

    embed_stage = EmbedStage(
        embedder=embedder
    )

    storage_stage = StorageStage(
        vector_store=vector_store,
        paper_store=paper_store
    )

    # ── Inline PDF Deletion + Metrics Hook ──
    def update_metrics_and_cleanup(paper, chunk_count):
        """Called by ConcurrentPipeline.on_success after each successful upsert."""
        # 1. Update monitor metrics
        monitor.increment("embedding", "pdfs_processed")
        monitor.increment("embedding", "chunks_embedded", chunk_count)
        monitor.heartbeat()

        # 2. Delete PDF immediately after successful storage
        if paper.pdf_path:
            pdf_path = Path(paper.pdf_path)
            if pdf_path.exists():
                try:
                    pdf_path.unlink()
                    logger.info(f"[CLEANUP] Inline: deleted {pdf_path.name}")
                except Exception as e:
                    logger.warning(f"[CLEANUP] Failed to delete {pdf_path.name}: {e}")

    # ── Wrap callback for manual import file movement ──
    if getattr(args, 'manual', False):
        success_callback = create_manual_import_success_callback(
            update_metrics_and_cleanup, manual_import_dir, monitor
        )
    else:
        success_callback = update_metrics_and_cleanup

    # ── Custom Retry Policies ──
    # Don't retry deterministic parsing errors (quality, invalid format)
    # These will NEVER succeed on retry, so we skip directly to DLQ to save CPU.
    custom_chunk_retry = RetryPolicy(
        stage="chunk", 
        max_retries=2, 
        base_delay=1.0,
        retryable_exceptions=(Exception,), 
        exclude_exceptions=(LowQualityExtractionError, InvalidPDFError)
    )

    # ── Multi-Process Workload Config ──
    parser_cfg = {
        'quality_threshold': ingest_config.get('quality_threshold', 0.7),
        'use_markdown': (ingest_config.get('pdf_parser') == "pymupdf4llm")
    }
    chunker_cfg = {
        'chunk_size': chunk_config.get('chunk_size', 800),
        'chunk_overlap': chunk_config.get('chunk_overlap', 150),
        'min_chunk_size': chunk_config.get('min_chunk_size', 100),
        'tokenizer': chunk_config.get('tokenizer', "cl100k_base")
    }

    # ── Assemble Concurrent Pipeline ──
    pipeline = ConcurrentPipeline(
        chunk_stage=chunk_stage,
        embed_stage=embed_stage,
        storage_stage=storage_stage,
        dlq=dlq,
        on_success=success_callback,
        chunk_workers=auto_params.get('parser_workers', ingest_config.get('max_workers', 4)),
        chunk_retry=custom_chunk_retry, # <--- USE FILTERED RETRY
        embed_batch_size=embedder.batch_size,
        parsed_queue_size=auto_params.get('queue_size_parsed', 100),
        embedded_queue_size=auto_params.get('queue_size_embedded', 100),
        parser_config=parser_cfg,
        chunker_config=chunker_cfg,
        # BM25 concurrent indexing
        bm25_index=bm25_index,
        paper_store=paper_store,
        bm25_batch_size=bm25_config.get('batch_size', 50),
        bm25_commit_interval=bm25_config.get('commit_interval', 5.0),
    )

    # ── SIGTERM Handler ──
    def _handle_sigterm(signum, frame):
        logger.info("SIGTERM received — initiating graceful shutdown...")
        stop_event.set()          # Stop DatabaseSource from yielding new items
        pipeline._shutdown.set()  # Stop ConcurrentPipeline worker threads

    signal.signal(signal.SIGTERM, _handle_sigterm)

    # ── Start BM25 Resume Background Thread (if needed) ──
    bm25_resume_thread = None
    if bm25_enabled and bm25_index is not None and pipeline.bm25_queue is not None:
        unindexed_count = len(paper_store.get_unindexed_bm25_papers(limit=1))
        if unindexed_count > 0:
            bm25_resume_thread = Thread(
                target=_resume_bm25_async,
                args=(paper_store, pipeline.bm25_queue, vector_store, stop_event),
                daemon=True,
                name="BM25ResumeWorker"
            )
            bm25_resume_thread.start()
            logger.info("[STARTUP] BM25 resume thread started in background")

    # ── Run Manual Import (if enabled) ──
    if getattr(args, 'manual', False):
        manual_count = run_manual_import(paper_store, config)
        logger.info(f"[MANUAL-IMPORT] Registered {manual_count} PDFs for processing")
        if manual_count == 0 and not args.stream:
            logger.info("[MANUAL-IMPORT] No new PDFs to process. Exiting.")
            return

    # ── Run Pipeline ──
    mode_label = 'STREAMING' if args.stream else 'BATCH'
    logger.info(f"Starting pipeline in {mode_label} mode...")
    monitor.start()

    is_manual = getattr(args, 'manual', False)

    # 1. Background Discovery Thread
    # Disable background API discovery in manual mode to guarantee restricted execution scope
    if not is_manual and (args.stream or getattr(args, 'embed_only', False)):
        discovery_thread = Thread(
            target=_discovery_worker,
            args=(discoverer, paper_store, config, stop_event),
            daemon=True
        )
        discovery_thread.start()
    elif is_manual:
        logger.info("[STARTUP] Manual mode: Bypassing background API discovery thread.")

    try:
        if getattr(args, 'manual', False):
            # ── MANUAL MODE: Loop until directory is empty ──
            iteration = 0
            max_iterations = 100  # Safety limit

            while iteration < max_iterations:
                iteration += 1
                logger.info(f"[MANUAL-IMPORT] Starting iteration {iteration}")

                # 1. Scan directory and register PDFs
                scanner = ManualImportScanner(paper_store, manual_import_dir)
                manual_count = scanner.scan_and_register(max_workers=4)
                logger.info(f"[MANUAL-IMPORT] Registered {manual_count} PDFs")

                # 2. Retry failed_parse PDFs
                retry_count = scanner.retry_failed_parses(max_workers=2)
                logger.info(f"[MANUAL-IMPORT] Retried {len(retry_count)} failed PDFs")

                # 3. Check if directory is empty
                if check_manual_import_completion(manual_import_dir):
                    logger.info(f"[MANUAL-IMPORT] Completion verified after {iteration} iterations")
                    break

                # 4. Process one batch
                monitor.metrics.current_phase = PipelinePhase.EMBEDDING.value
                input_stream = source.stream()
                logger.info("Manual mode: Bypassing DownloadStage (papers already on disk).")
                pipeline.run(input_stream, limit=args.limit or 50)

                # 5. Check completion again
                if check_manual_import_completion(manual_import_dir):
                    logger.info(f"[MANUAL-IMPORT] Completion verified after {iteration} iterations")
                    break

                # 6. Small delay before next iteration
                time.sleep(2)

            if iteration >= max_iterations:
                logger.warning(f"[MANUAL-IMPORT] Reached max iterations ({max_iterations})")
        else:
            # ── NORMAL MODE: Run once ──
            monitor.metrics.current_phase = PipelinePhase.EMBEDDING.value
            input_stream = source.stream()

            if not args.embed_only:
                monitor.metrics.current_phase = PipelinePhase.DOWNLOAD.value
                logger.info("Integrating DownloadStage...")
                input_stream = download_stage.process(input_stream)

            pipeline.run(input_stream, limit=args.limit)

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user.")
        monitor.stop(graceful=False, status=PipelineStatus.STOPPED)
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        monitor.stop(graceful=False, status=PipelineStatus.FAILED)
        sys.exit(1)
    finally:
        monitor.stop(graceful=True)

        # Wait for BM25 resume thread to finish (if running)
        if bm25_resume_thread is not None and bm25_resume_thread.is_alive():
            logger.info("[SHUTDOWN] Waiting for BM25 resume thread...")
            stop_event.set()  # Signal resume thread to stop
            bm25_resume_thread.join(timeout=10.0)
            if bm25_resume_thread.is_alive():
                logger.warning("[SHUTDOWN] BM25 resume thread did not stop gracefully")

        # Always clean up failed manual imports (regardless of --manual flag)
        try:
            import_dir = Path(config.get('system', {}).get('manual_import_dir', 'DataBase/ManualImport'))
            cleanup_failed_manual_imports(paper_store, import_dir)
        except Exception as e:
            logger.warning(f"[CLEANUP] Failed to run manual import cleanup: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SME Autonomous Update Pipeline")
    parser.add_argument("--stream", action="store_true", help="Run in continuous streaming mode")
    parser.add_argument("--embed-only", action="store_true", help="Only process already downloaded papers")
    parser.add_argument("--limit", type=int, help="Limit number of papers to process")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for database polling")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument("--test", action="store_true", help="Run in test mode")
    parser.add_argument("--manual", action="store_true", help="Process PDFs from DataBase/ManualImport directory")

    args = parser.parse_args()
    run_pipeline(args)
