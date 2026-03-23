"""
SME Research Assistant - Concurrent Pipeline

Queue-based pipeline runner that replaces the synchronous generator chain
with concurrent worker threads. Stages overlap: while embed processes paper A,
chunk is parsing paper B, and store is upserting paper C.

Architecture:
    source_iterator → [chunk_worker] → Q1 → [embed_worker] → Q2 → [store_worker] → done

Thread safety:
    - Bounded queues provide backpressure (blocking put when full)
    - None sentinel propagates shutdown signal through the queue chain
    - Each worker catches per-item exceptions and routes failures to DLQ
    - Metrics counters use threading.Lock for atomicity
"""

import logging
import time
import threading
from queue import Queue, Empty as QueueEmpty, Full as QueueFull
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed, Future
from typing import Iterator, Optional, Callable, Dict, Any, List, Tuple
from dataclasses import dataclass, field

from .streaming import PipelineItem, PipelineStage
from src.core.interfaces import Chunk
from .retry_policy import RetryPolicy, RetryExhausted, CHUNK_RETRY, EMBED_RETRY, STORE_RETRY
from .dead_letter_queue import DeadLetterQueue
from .chunk_worker import process_paper_to_chunks
from .bm25_worker import BM25Worker, BM25IndexItem

logger = logging.getLogger(__name__)

def _worker_parse_paper(
    pdf_path: str,
    doi: str,
    title: str,
    authors: List[str],
    year: int,
    venue: str,
    citation_count: int,
    apa_reference: str,
    parser_config: Dict[str, Any],
    chunker_config: Dict[str, Any]
) -> List[Chunk]:
    """Module-level worker function (required for pickling on Windows)."""
    return process_paper_to_chunks(
        pdf_path=pdf_path,
        paper_metadata={
            "doi": doi,
            "title": title,
            "authors": authors,
            "year": year,
            "venue": venue,
            "citation_count": citation_count,
            "apa_reference": apa_reference
        },
        parser_config=parser_config,
        chunker_config=chunker_config
    )

# Sentinel value to signal thread shutdown
_SENTINEL = None

# Queue timeout configuration (reduced from 300s to prevent long hangs)
QUEUE_PUT_TIMEOUT = 60  # seconds per attempt
QUEUE_PUT_MAX_RETRIES = 3  # max retry attempts


def _safe_queue_put(queue: Queue, item, timeout: float = QUEUE_PUT_TIMEOUT,
                    max_retries: int = QUEUE_PUT_MAX_RETRIES,
                    shutdown_event: Optional[threading.Event] = None) -> bool:
    """
    Put item in queue with retry logic and backoff.

    Args:
        queue: Target queue
        item: Item to put
        timeout: Timeout per attempt (default 60s)
        max_retries: Max retry attempts (default 3)
        shutdown_event: Optional shutdown event to check between retries

    Returns:
        True if item was put successfully, False if shutdown requested

    Raises:
        RuntimeError if all retries exhausted
    """
    for attempt in range(max_retries):
        if shutdown_event and shutdown_event.is_set():
            logger.info(f"[QUEUE-PUT] Shutdown requested, abandoning put after {attempt} attempts")
            return False
        try:
            queue.put(item, timeout=timeout)
            return True
        except QueueFull:
            if attempt < max_retries - 1:
                wait_time = min(2 ** attempt, 10)  # Exponential backoff, cap at 10s
                logger.warning(
                    f"[QUEUE-PUT] Queue full, retry {attempt + 1}/{max_retries} "
                    f"(waiting {wait_time}s)"
                )
                time.sleep(wait_time)
            else:
                raise RuntimeError(
                    f"Failed to put item in queue after {max_retries} retries "
                    f"(total wait: {timeout * max_retries}s)"
                )
    return False


@dataclass
class PipelineMetrics:
    """Thread-safe metrics counters for the concurrent pipeline."""
    papers_parsed: int = 0
    papers_embedded: int = 0
    papers_stored: int = 0
    chunks_embedded: int = 0
    parse_errors: int = 0
    embed_errors: int = 0
    store_errors: int = 0
    dlq_items: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    
    def increment(self, field_name: str, amount: int = 1):
        with self._lock:
            current = getattr(self, field_name, 0)
            setattr(self, field_name, current + amount)
    
    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return {
                "papers_parsed": self.papers_parsed,
                "papers_embedded": self.papers_embedded,
                "papers_stored": self.papers_stored,
                "chunks_embedded": self.chunks_embedded,
                "parse_errors": self.parse_errors,
                "embed_errors": self.embed_errors,
                "store_errors": self.store_errors,
                "dlq_items": self.dlq_items,
            }


class ConcurrentPipeline:
    """
    Queue-based concurrent pipeline that overlaps chunk/embed/store stages.
    
    Each stage runs in its own thread. Bounded queues between stages provide
    natural backpressure — if embed is slow, chunk blocks on Q1.put() until
    there's room, preventing unbounded memory growth.
    
    Args:
        chunk_stage: ChunkStage instance (parse PDF + split)
        embed_stage: EmbedStage instance (GPU/Ollama embedding)
        storage_stage: StorageStage instance (Qdrant upsert)
        dlq: DeadLetterQueue instance for failed items
        parsed_queue_size: Max items in Q1 (chunk → embed)
        embedded_queue_size: Max items in Q2 (embed → store)
        on_success: Optional callback(paper, num_chunks) on successful storage
        chunk_workers: Number of concurrent PDF parse threads (default 4)
        embed_batch_size: Max chunks to accumulate across papers before embedding (default 128)
        embed_batch_timeout: Seconds to wait before flushing a partial batch (default 2.0)
        chunk_retry: Retry policy for chunk stage
        embed_retry: Retry policy for embed stage  
        store_retry: Retry policy for store stage
    """
    
    def __init__(
        self,
        chunk_stage: PipelineStage,
        embed_stage: PipelineStage,
        storage_stage: PipelineStage,
        dlq: DeadLetterQueue,
        parsed_queue_size: int = 10,
        embedded_queue_size: int = 50,
        on_success: Optional[Callable] = None,
        chunk_workers: int = 4,
        embed_batch_size: int = 128,
        embed_batch_timeout: float = 2.0,
        chunk_retry: Optional[RetryPolicy] = None,
        embed_retry: Optional[RetryPolicy] = None,
        store_retry: Optional[RetryPolicy] = None,
        parser_config: Optional[Dict] = None,
        chunker_config: Optional[Dict] = None,
        bm25_index: Optional[Any] = None,
        paper_store: Optional[Any] = None,
        bm25_batch_size: int = 50,
        bm25_commit_interval: float = 5.0,
    ):
        self.chunk_stage = chunk_stage
        self.embed_stage = embed_stage
        self.storage_stage = storage_stage
        self.dlq = dlq
        self.on_success = on_success
        self.chunk_workers = max(1, chunk_workers)
        self.embed_batch_size = embed_batch_size
        self.embed_batch_timeout = embed_batch_timeout
        self.parser_config = parser_config or {}
        self.chunker_config = chunker_config or {}

        # BM25 concurrent indexing
        self.bm25_index = bm25_index
        self.paper_store = paper_store
        self.bm25_batch_size = bm25_batch_size
        self.bm25_commit_interval = bm25_commit_interval

        # Bounded queues
        self.input_queue = Queue(maxsize=parsed_queue_size)     # Q0: source → chunk
        self.parsed_queue = Queue(maxsize=parsed_queue_size)    # Q1: chunk → embed
        self.embedded_queue = Queue(maxsize=embedded_queue_size)  # Q2: embed → store

        # BM25 queue (only if bm25_index provided)
        self.bm25_queue: Optional[Queue] = Queue(maxsize=200) if bm25_index else None

        # Retry policies
        self.chunk_retry = chunk_retry or CHUNK_RETRY
        self.embed_retry = embed_retry or EMBED_RETRY
        self.store_retry = store_retry or STORE_RETRY

        # Metrics
        self.metrics = PipelineMetrics()

        # Shutdown coordination
        self._shutdown = threading.Event()
        
    def run(self, source_iterator: Iterator[PipelineItem], limit: Optional[int] = None):
        """
        Run the concurrent pipeline until source is exhausted or limit reached.
        
        This method blocks until all workers complete. Items flow:
        source → chunk_worker → Q1 → embed_worker → Q2 → store_worker → done
        
        Args:
            source_iterator: Iterator of PipelineItem from DatabaseSource
            limit: Max papers to process (None = no limit)
        """
        start_time = time.time()
        
        bm25_enabled = self.bm25_index is not None and self.paper_store is not None
        logger.info(
            f"[CONCURRENT] Starting pipeline | "
            f"Q1_size={self.parsed_queue.maxsize}, "
            f"Q2_size={self.embedded_queue.maxsize}, "
            f"chunk_workers={self.chunk_workers}, "
            f"embed_batch_size={self.embed_batch_size}, "
            f"embed_batch_timeout={self.embed_batch_timeout}s, "
            f"bm25_enabled={bm25_enabled}, "
            f"limit={limit}"
        )

        # Start BM25 worker thread (if enabled)
        bm25_worker = None
        bm25_thread = None
        if bm25_enabled:
            bm25_worker = BM25Worker(
                bm25_index=self.bm25_index,
                paper_store=self.paper_store,
                queue=self.bm25_queue,
                batch_size=self.bm25_batch_size,
                commit_interval=self.bm25_commit_interval,
            )
            bm25_thread = threading.Thread(
                target=bm25_worker.run,
                name="BM25Worker",
                daemon=False
            )
            bm25_thread.start()

        # Start worker threads
        feeder_thread = threading.Thread(
            target=self._feeder_worker,
            args=(source_iterator,),
            name="FeederWorker",
            daemon=False
        )
        chunk_thread = threading.Thread(
            target=self._chunk_worker,
            args=(limit,),
            name="ChunkWorker",
            daemon=False
        )
        embed_thread = threading.Thread(
            target=self._embed_worker,
            name="EmbedWorker",
            daemon=False
        )
        store_thread = threading.Thread(
            target=self._store_worker,
            name="StoreWorker",
            daemon=False
        )
        
        feeder_thread.start()
        chunk_thread.start()
        embed_thread.start()
        store_thread.start()
        
        # Log progress periodically while waiting
        try:
            while store_thread.is_alive():
                store_thread.join(timeout=10.0)
                if store_thread.is_alive():
                    elapsed = time.time() - start_time
                    m = self.metrics.snapshot()
                    rate_per_day = (m['papers_stored'] / elapsed * 86400) if elapsed > 0 else 0
                    logger.info(
                        f"[CONCURRENT] Progress | {rate_per_day:.0f} papers/day | "
                        f"elapsed={elapsed:.0f}s, "
                        f"parsed={m['papers_parsed']}, "
                        f"embedded={m['papers_embedded']}, "
                        f"stored={m['papers_stored']}, "
                        f"chunks={m['chunks_embedded']}, "
                        f"errors={m['parse_errors']+m['embed_errors']+m['store_errors']}, "
                        f"dlq={m['dlq_items']}, "
                        f"Q1={self.parsed_queue.qsize()}/{self.parsed_queue.maxsize}, "
                        f"Q2={self.embedded_queue.qsize()}/{self.embedded_queue.maxsize}"
                    )
        except KeyboardInterrupt:
            logger.warning("[CONCURRENT] Interrupted by user, shutting down...")
            self._shutdown.set()
            # Put sentinels to unblock workers
            try:
                self.input_queue.put(_SENTINEL, timeout=1)
            except Exception:
                pass
            try:
                self.parsed_queue.put(_SENTINEL, timeout=1)
            except Exception:
                pass
            try:
                self.embedded_queue.put(_SENTINEL, timeout=1)
            except Exception:
                pass
            # BM25 queue sentinel
            if self.bm25_queue:
                try:
                    self.bm25_queue.put(_SENTINEL, timeout=1)
                except Exception:
                    pass

        # Wait for all threads to finish
        feeder_thread.join(timeout=30.0)
        chunk_thread.join(timeout=30.0)
        embed_thread.join(timeout=30.0)
        store_thread.join(timeout=30.0)

        # Wait for BM25 worker to finish (give extra time to flush)
        if bm25_thread:
            # Send sentinel if not already sent
            if self.bm25_queue:
                try:
                    self.bm25_queue.put(_SENTINEL, timeout=1)
                except Exception:
                    pass
            bm25_thread.join(timeout=60.0)
            if bm25_thread.is_alive():
                logger.warning("[CONCURRENT] BM25Worker still running, signaling shutdown...")
                if bm25_worker:
                    bm25_worker.shutdown()  # Set shutdown event
                bm25_thread.join(timeout=30.0)  # Second chance
                if bm25_thread.is_alive():
                    logger.error(
                        "[CONCURRENT] BM25Worker failed to stop after 90s total - "
                        "may leave Tantivy index locked"
                    )
        
        elapsed = time.time() - start_time
        m = self.metrics.snapshot()
        
        logger.info(
            f"[CONCURRENT] Pipeline complete | "
            f"elapsed={elapsed:.1f}s, "
            f"parsed={m['papers_parsed']}, "
            f"embedded={m['papers_embedded']}, "
            f"stored={m['papers_stored']}, "
            f"chunks={m['chunks_embedded']}, "
            f"errors={m['parse_errors']+m['embed_errors']+m['store_errors']}, "
            f"dlq={m['dlq_items']}"
        )
        
        # Log DLQ summary
        dlq_summary = self.dlq.summary()
        if dlq_summary:
            logger.warning(f"[CONCURRENT] DLQ summary: {dlq_summary}")
    
    def _feeder_worker(self, source_iterator: Iterator[PipelineItem]):
        """
        Background thread: pulls from source_iterator and puts into input_queue.
        This prevents synchronous source/download from blocking the worker threads.
        """
        logger.info("[FEEDER-WORKER] Started")
        try:
            for item in source_iterator:
                if self._shutdown.is_set():
                    break
                self.input_queue.put(item)
        except Exception as e:
            if not self._shutdown.is_set():
                logger.error(f"[FEEDER-WORKER] Fatal error: {e}", exc_info=True)
        finally:
            self.input_queue.put(_SENTINEL)
            logger.info("[FEEDER-WORKER] Stopped")
    
    def _chunk_worker(self, limit: Optional[int]):
        """
        Worker thread: reads from input_queue, parses + chunks concurrently, writes to Q1.
        Uses ThreadPoolExecutor for parallel PDF parsing (CPU-bound).
        Sends None sentinel when done.
        
        Memory bound: at most `chunk_workers` papers being parsed simultaneously.
        Backpressure: Q1.put(timeout=30) blocks if embed_worker can't keep up.
        """
        logger.info(f"[CHUNK-WORKER] Started with {self.chunk_workers} parallel processes (GIL bypass)")
        processed = 0
        
        try:
            with ProcessPoolExecutor(max_workers=self.chunk_workers) as executor:
                # Dict of pending futures → original PipelineItem
                pending: Dict[Future, PipelineItem] = {}
                input_done = False
                
                while not self._shutdown.is_set():
                    # --- SUBMIT: fill pending futures up to chunk_workers ---
                    while (len(pending) < self.chunk_workers 
                           and not input_done 
                           and not self._shutdown.is_set()):
                        try:
                            # Use zero timeout if we have jobs running to avoid blocking submission
                            # Use small timeout if we are empty to avoid busy-loop
                            timeout = 0.001 if pending else 1.0
                            item = self.input_queue.get(timeout=timeout)
                        except QueueEmpty:
                            # If queue is empty, break inner loop to collect finished jobs
                            break
                        
                        if item is _SENTINEL:
                            input_done = True
                            break
                        
                        if not item.is_valid:
                            logger.warning(f"[CHUNK-WORKER] Skipping invalid item: {item.id}")
                            continue
                        
                        # Submit parse job with retry logic inside the submit
                        # We pass discrete fields to maximize picklability
                        paper = item.payload
                        future = executor.submit(
                            self.chunk_retry.execute,
                            _worker_parse_paper,
                            pdf_path=paper.pdf_path,
                            doi=paper.doi,
                            title=paper.title,
                            authors=paper.authors,
                            year=paper.year,
                            venue=paper.venue,
                            citation_count=paper.citation_count,
                            apa_reference=paper.apa_reference,
                            parser_config=self.parser_config,
                            chunker_config=self.chunker_config
                        )
                        pending[future] = item
                    
                    # If nothing pending and source done, we're finished
                    if not pending:
                        break
                    
                    # --- COLLECT: wait for at least one to complete ---
                    done_futures = set()
                    try:
                        for f in as_completed(pending, timeout=5.0):
                            done_futures.add(f)
                            item = pending[f]
                            
                            try:
                                chunks = f.result()
                                # Successful parse: update status in HOST thread (safe)
                                item.metadata['paper'] = item.payload
                                item.payload = chunks
                                
                                # Checkpoint DB status
                                try:
                                    self.chunk_stage.paper_store.update_status(item.id, "chunked")
                                except Exception as db_err:
                                    logger.warning(f"[CHUNK-WORKER] DB update failed for {item.id}: {db_err}")

                                if not _safe_queue_put(
                                    self.parsed_queue, item,
                                    shutdown_event=self._shutdown
                                ):
                                    logger.info(f"[CHUNK-WORKER] Shutdown during queue put for {item.id}")
                                    break
                                self.metrics.increment("papers_parsed")
                                processed += 1
                                
                                logger.info(f"[CHUNK-COMPLETE] Paper={item.id}, Chunks={len(chunks)}")

                                if limit and processed >= limit:
                                    logger.info(f"[CHUNK-WORKER] Limit reached ({limit})")
                                    input_done = True
                                    break
                            except RetryExhausted as e:
                                logger.error(f"[CHUNK-WORKER] Retry exhausted for {item.id}: {e}")
                                try:
                                    self.chunk_stage.paper_store.update_status(item.id, "failed_parse")
                                except Exception as db_err:
                                    logger.warning(f"[CHUNK-WORKER] Failed to mark {item.id} as failed in DB: {db_err}")
                                    
                                self.dlq.push(
                                    paper_id=item.id, stage="chunk",
                                    error=str(e), retry_count=-1
                                )
                                self.metrics.increment("parse_errors")
                                self.metrics.increment("dlq_items")
                                
                            except Exception as e:
                                logger.error(f"[CHUNK-WORKER] Error for {item.id}: {e}", exc_info=True)
                                try:
                                    self.chunk_stage.paper_store.update_status(item.id, "failed_parse")
                                except Exception as db_err:
                                    logger.warning(f"[CHUNK-WORKER] Failed to mark {item.id} as failed in DB: {db_err}")
                                    
                                self.dlq.push(paper_id=item.id, stage="chunk", error=str(e))
                                self.metrics.increment("parse_errors")
                                self.metrics.increment("dlq_items")
                            
                            # Only collect up to what's done to avoid blocking
                            if len(done_futures) >= len(pending):
                                break
                    except TimeoutError:
                        # as_completed() raised TimeoutError — some futures are still running.
                        # This is NORMAL for large PDFs. Just collect what's done and loop back;
                        # the unfinished futures stay in pending and will be collected next iteration.
                        logger.debug(f"[CHUNK-WORKER] as_completed timeout: {len(done_futures)} done, "
                                     f"{len(pending) - len(done_futures)} still running")
                    
                    # Remove collected futures
                    for f in done_futures:
                        del pending[f]
                    
        except Exception as e:
            logger.error(f"[CHUNK-WORKER] Fatal error: {e}", exc_info=True)
        finally:
            self.parsed_queue.put(_SENTINEL)
            logger.info(f"[CHUNK-WORKER] Stopped | parsed={processed}")
    
    def _embed_worker(self):
        """
        Worker thread: reads from Q1, batches chunks across papers, embeds
        via GPU/Ollama, splits results back to per-paper, writes to Q2.
        
        Cross-paper batching: accumulates chunks from multiple papers until
        embed_batch_size or embed_batch_timeout, then embeds all at once.
        This maximizes GPU tensor core occupancy.
        
        Memory bound: at most embed_batch_size chunks (~3MB text + ~2MB embeddings).
        Backpressure: Q2.put(timeout=30) blocks if store_worker can't keep up.
        """
        logger.info(
            f"[EMBED-WORKER] Started | batch_size={self.embed_batch_size}, "
            f"timeout={self.embed_batch_timeout}s"
        )
        processed = 0
        total_chunks = 0
        
        # Batch accumulators
        # Each entry: (PipelineItem, start_idx_in_batch, num_chunks)
        batch_items: List[Tuple[PipelineItem, int, int]] = []
        batch_texts: List[str] = []
        batch_deadline = time.monotonic() + self.embed_batch_timeout
        
        def _flush_batch():
            """Embed accumulated batch and dispatch results to Q2."""
            nonlocal processed, total_chunks, batch_items, batch_texts, batch_deadline
            
            if not batch_texts:
                return
            
            n_papers = len(set(b['item'].id for b in batch_items))
            n_chunks = len(batch_texts)
            
            try:
                t0 = time.perf_counter()
                all_vectors = self.embed_stage.embedder.embed(batch_texts)
                elapsed = time.perf_counter() - t0
                
                if len(all_vectors) != n_chunks:
                    raise RuntimeError(
                        f"Embedding mismatch: got {len(all_vectors)} vectors "
                        f"for {n_chunks} chunks"
                    )
                
                cps = n_chunks / elapsed if elapsed > 0 else 0
                logger.debug(
                    f"[EMBED-WORKER] Batch embedded: {n_chunks} chunks from "
                    f"{n_papers} papers in {elapsed:.2f}s ({cps:.0f} chunks/sec)"
                )
                
                # Assign vectors back to each paper's chunks
                for b_entry in batch_items:
                    item = b_entry['item']
                    start = b_entry['start_idx']
                    num = b_entry['num']
                    offset = b_entry['offset']
                    is_last = b_entry['is_last']
                    
                    paper_vectors = all_vectors[start:start + num]
                    chunks = item.payload
                    
                    # Fill specifically the range of chunks handled in this batch
                    for i, vec in enumerate(paper_vectors):
                        chunks[offset + i].embedding = vec
                    
                    # Only dispatch to storage once the entire paper is done
                    if is_last:
                        if not _safe_queue_put(
                            self.embedded_queue, item,
                            shutdown_event=self._shutdown
                        ):
                            logger.info(f"[EMBED-WORKER] Shutdown during queue put for {item.id}")
                            break
                        self.metrics.increment("papers_embedded")
                        processed += 1
                    
                    self.metrics.increment("chunks_embedded", num)
                    total_chunks += num
                    
            except Exception as e:
                logger.error(f"[EMBED-WORKER] Batch embed failed: {e}", exc_info=True)
                # Send each item to DLQ individually (only once per paper)
                sent_to_dlq = set()
                for b_entry in batch_items:
                    item = b_entry['item']
                    if item.id not in sent_to_dlq:
                        self.dlq.push(paper_id=item.id, stage="embed", error=str(e))
                        self.metrics.increment("embed_errors")
                        self.metrics.increment("dlq_items")
                        sent_to_dlq.add(item.id)
            
            # Reset accumulators
            batch_items = []
            batch_texts = []
            batch_deadline = time.monotonic() + self.embed_batch_timeout
        
        try:
            while True:
                if self._shutdown.is_set():
                    logger.info("[EMBED-WORKER] Shutdown signal received")
                    break
                
                # Calculate remaining time until batch timeout
                remaining = max(0.1, batch_deadline - time.monotonic())
                
                try:
                    item = self.parsed_queue.get(timeout=min(remaining, 2.0))
                except QueueEmpty:
                    # Timeout — flush whatever we have (partial batch)
                    if batch_texts:
                        _flush_batch()
                    continue
                
                if item is _SENTINEL:
                    logger.info("[EMBED-WORKER] Received sentinel, flushing final batch")
                    _flush_batch()
                    break
                
                if not item.is_valid:
                    continue
                
                # Accumulate this paper's chunks into the batch (Split if necessary)
                chunks = item.payload
                if not isinstance(chunks, list) or not chunks:
                    logger.error(f"[EMBED-WORKER] Paper {item.id} has 0 valid text chunks. Sending to DLQ.")
                    try:
                        # Try to mark as failed in DB
                        self.chunk_stage.paper_store.update_status(item.id, "failed_parse")
                    except Exception as db_err:
                        logger.warning(f"[EMBED-WORKER] Failed to update DB status for {item.id}: {db_err}")
                        
                    # Push directly to dead letter queue
                    self.dlq.push(paper_id=item.id, stage="embed", error="Failed to extract valid text chunks")
                    self.metrics.increment("embed_errors")
                    self.metrics.increment("dlq_items")
                    continue
                
                texts = [c.text for c in chunks]
                curr_offset = 0
                
                while curr_offset < len(texts):
                    space = self.embed_batch_size - len(batch_texts)
                    
                    # If current batch is full, flush it first
                    if space <= 0:
                        _flush_batch()
                        space = self.embed_batch_size
                    
                    # Take as much as fits
                    slice_end = min(curr_offset + space, len(texts))
                    chunk_slice = texts[curr_offset:slice_end]
                    
                    start_idx_in_batch = len(batch_texts)
                    num_in_slice = len(chunk_slice)
                    is_last = (slice_end == len(texts))
                    
                    batch_items.append({
                        'item': item,
                        'start_idx': start_idx_in_batch,
                        'num': num_in_slice,
                        'offset': curr_offset,
                        'is_last': is_last
                    })
                    batch_texts.extend(chunk_slice)
                    curr_offset = slice_end
                    
                    # If we just reached the limit, flush
                    if len(batch_texts) >= self.embed_batch_size:
                        _flush_batch()
                    
        except Exception as e:
            logger.error(f"[EMBED-WORKER] Fatal error: {e}", exc_info=True)
            # Try to flush remaining
            try:
                _flush_batch()
            except Exception:
                pass
        finally:
            self.embedded_queue.put(_SENTINEL)
            logger.info(f"[EMBED-WORKER] Stopped | papers={processed}, chunks={total_chunks}")
    
    def _store_worker(self):
        """
        Worker thread: reads from Q2, upserts to Qdrant, updates paper status.
        """
        logger.info("[STORE-WORKER] Started")
        processed = 0
        
        try:
            while True:
                if self._shutdown.is_set():
                    logger.info("[STORE-WORKER] Shutdown signal received")
                    break
                
                try:
                    item = self.embedded_queue.get(timeout=5)
                except QueueEmpty:
                    continue  # No items yet, keep polling
                
                if item is _SENTINEL:
                    logger.info("[STORE-WORKER] Received sentinel, finishing")
                    break
                
                try:
                    def _do_store(pipeline_item):
                        results = list(self.storage_stage.process(iter([pipeline_item])))
                        if not results:
                            raise RuntimeError(f"StorageStage returned no results for {pipeline_item.id}")
                        result = results[0]
                        # If stage caught error internally, re-raise for retry
                        if not result.is_valid:
                            raise RuntimeError(result.error or f"StorageStage failed for {pipeline_item.id}")
                        return result
                    
                    stored_item = self.store_retry.execute(_do_store, item)
                    
                    if stored_item.is_valid:
                        paper = stored_item.metadata.get('paper')
                        chunks = stored_item.payload
                        num_chunks = len(chunks) if isinstance(chunks, list) else 0

                        self.metrics.increment("papers_stored")
                        processed += 1

                        if self.on_success and paper:
                            try:
                                self.on_success(paper, num_chunks)
                            except Exception as cb_err:
                                logger.warning(f"[STORE-WORKER] on_success callback error: {cb_err}")

                        # Send to BM25 worker for concurrent indexing
                        if self.bm25_queue is not None and paper and isinstance(chunks, list):
                            try:
                                bm25_item = BM25IndexItem(
                                    paper_unique_id=paper.unique_id,
                                    chunk_ids=[c.chunk_id for c in chunks],
                                    texts=[c.text for c in chunks]
                                )
                                self.bm25_queue.put(bm25_item, timeout=30)
                            except Exception as bm25_err:
                                logger.warning(f"[STORE-WORKER] Failed to queue BM25 item: {bm25_err}")

                        logger.info(
                            f"✅ Stored Paper {paper.unique_id if paper else item.id} "
                            f"({num_chunks} chunks)"
                        )
                    else:
                        self.dlq.push(
                            paper_id=item.id,
                            stage="store",
                            error=stored_item.error or "Unknown store error"
                        )
                        self.metrics.increment("store_errors")
                        self.metrics.increment("dlq_items")
                        
                except RetryExhausted as e:
                    logger.error(f"[STORE-WORKER] Retry exhausted for {item.id}: {e}")
                    self.dlq.push(
                        paper_id=item.id,
                        stage="store",
                        error=str(e),
                        retry_count=-1
                    )
                    self.metrics.increment("store_errors")
                    self.metrics.increment("dlq_items")
                    
                except Exception as e:
                    logger.error(f"[STORE-WORKER] Unexpected error for {item.id}: {e}", exc_info=True)
                    self.dlq.push(paper_id=item.id, stage="store", error=str(e))
                    self.metrics.increment("store_errors")
                    self.metrics.increment("dlq_items")
                    
        except Exception as e:
            logger.error(f"[STORE-WORKER] Fatal error: {e}", exc_info=True)
        finally:
            logger.info(f"[STORE-WORKER] Stopped | stored={processed}")
