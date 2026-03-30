"""
SME Research Assistant - BM25 Worker

Background worker that indexes papers in Tantivy BM25 index.
Runs concurrently with the main pipeline without blocking embedding/storage.

Architecture:
    embedded_queue → [StoreWorker] → (on_success) → bm25_queue → [BM25Worker] → Tantivy
                                                                       ↓
                                                           update bm25_indexed=1
"""

import logging
import time
import threading
from queue import Queue, Empty as QueueEmpty
from dataclasses import dataclass
from typing import List, Optional, Any

logger = logging.getLogger(__name__)

# Sentinel value to signal worker shutdown
_SENTINEL = None


@dataclass
class BM25IndexItem:
    """
    Item passed to BM25Worker for indexing.

    Contains the paper's unique_id and all chunk data needed for BM25 indexing.
    This decouples BM25 indexing from the main pipeline - chunks are copied here
    after successful Qdrant upsert.
    """
    paper_unique_id: str
    chunk_ids: List[str]
    texts: List[str]


class BM25Worker:
    """
    Background worker that indexes papers in Tantivy.

    Runs in its own thread, consuming from bm25_queue. Uses batch accumulation
    with periodic commits to balance throughput and durability.

    Features:
        - Batch accumulation: waits for batch_size items or commit_interval timeout
        - Atomic commits: all chunks in a batch are committed together
        - SQLite tracking: marks papers as bm25_indexed after commit
        - Graceful shutdown: flushes remaining items on sentinel

    Args:
        bm25_index: TantivyBM25Index instance
        paper_store: PaperStore instance for marking indexed papers
        queue: Input queue receiving BM25IndexItem objects
        batch_size: Number of papers to accumulate before committing (default 50)
        commit_interval: Max seconds to wait before flushing partial batch (default 5.0)
        heap_size_mb: Tantivy writer heap size in MB (default 64)
    """

    def __init__(
        self,
        bm25_index: Any,
        paper_store: Any,
        queue: Queue,
        batch_size: int = 50,
        commit_interval: float = 5.0,
        heap_size_mb: int = 64
    ):
        self.bm25_index = bm25_index
        self.paper_store = paper_store
        self.queue = queue
        self.batch_size = batch_size
        self.commit_interval = commit_interval
        self.heap_size_mb = heap_size_mb

        # Metrics
        self.papers_indexed = 0
        self.chunks_indexed = 0
        self.commit_count = 0
        self._lock = threading.Lock()

        # Shutdown flag
        self._shutdown = threading.Event()

        # Persistent writer (reused across batches to avoid LockBusy errors)
        self._writer = None

    def _acquire_writer(self):
        """Acquire Tantivy writer (called once at start)."""
        import tantivy
        self._writer = self.bm25_index.tantivy_index.writer(
            heap_size=self.heap_size_mb * 1024 * 1024
        )
        logger.info("[BM25-WORKER] Acquired Tantivy writer")

    def _release_writer(self):
        """Release Tantivy writer and clean up file locks."""
        if self._writer is not None:
            try:
                # Commit any pending changes
                self._writer.commit()
            except Exception as e:
                logger.warning(f"[BM25-WORKER] Final commit warning: {e}")
            try:
                del self._writer
                self._writer = None
                import gc
                gc.collect()
                # Reload index to release any lingering file handles
                self.bm25_index.tantivy_index.reload()
                logger.info("[BM25-WORKER] Released Tantivy writer")
            except Exception as e:
                logger.warning(f"[BM25-WORKER] Writer cleanup warning: {e}")

    def run(self):
        """
        Main loop - batch accumulation with periodic commits.

        Runs until sentinel is received or shutdown event is set.
        On exit, flushes any remaining items in the batch.

        CRITICAL: Uses a SINGLE persistent writer across all batches to avoid
        LockBusy errors on Windows. Writer is acquired once at start and
        released only on shutdown.
        """
        logger.info(
            f"[BM25-WORKER] Started | batch_size={self.batch_size}, "
            f"commit_interval={self.commit_interval}s, heap={self.heap_size_mb}MB"
        )

        batch: List[BM25IndexItem] = []
        batch_deadline = time.monotonic() + self.commit_interval

        try:
            # Acquire writer ONCE for the entire run
            self._acquire_writer()

            while not self._shutdown.is_set():
                # Calculate remaining time until batch timeout
                remaining = max(0.1, batch_deadline - time.monotonic())

                try:
                    item = self.queue.get(timeout=min(remaining, 1.0))
                except QueueEmpty:
                    # Timeout - flush if we have items and deadline passed
                    if batch and time.monotonic() >= batch_deadline:
                        self._flush_batch(batch)
                        batch = []
                        batch_deadline = time.monotonic() + self.commit_interval
                    continue

                # Check for sentinel
                if item is _SENTINEL:
                    logger.info("[BM25-WORKER] Received sentinel, flushing final batch")
                    if batch:
                        self._flush_batch(batch)
                    break

                # Accumulate item
                batch.append(item)

                # Flush if batch is full
                if len(batch) >= self.batch_size:
                    self._flush_batch(batch)
                    batch = []
                    batch_deadline = time.monotonic() + self.commit_interval

        except Exception as e:
            logger.error(f"[BM25-WORKER] Fatal error: {e}", exc_info=True)
            # Try to flush remaining batch
            if batch:
                try:
                    self._flush_batch(batch)
                except Exception:
                    logger.error("[BM25-WORKER] Failed to flush batch on error")
        finally:
            # CRITICAL: Always release writer on exit
            self._release_writer()
            with self._lock:
                logger.info(
                    f"[BM25-WORKER] Stopped | papers={self.papers_indexed}, "
                    f"chunks={self.chunks_indexed}, commits={self.commit_count}"
                )

    def _flush_batch(self, batch: List[BM25IndexItem]):
        """
        Commit batch to Tantivy and mark papers as indexed in SQLite.

        Uses the persistent writer (self._writer) that was acquired once in run().
        This avoids LockBusy errors that occur when creating/destroying writers
        for each batch.

        This is an atomic operation - either all items in the batch are
        committed and marked, or none are (on error).
        """
        if not batch:
            return

        if self._writer is None:
            logger.error("[BM25-WORKER] No writer available - skipping batch")
            return

        start_time = time.perf_counter()
        total_chunks = sum(len(item.chunk_ids) for item in batch)
        paper_ids = [item.paper_unique_id for item in batch]

        chunks_added = 0
        try:
            import tantivy

            # Add all documents using the persistent writer
            for item in batch:
                for chunk_id, text in zip(item.chunk_ids, item.texts):
                    if not text.strip():
                        continue
                    try:
                        doc_dict = {"id": str(chunk_id), "text": text}
                        self._writer.add_document(
                            tantivy.Document.from_dict(doc_dict, self.bm25_index.schema)
                        )
                        chunks_added += 1
                    except Exception as e:
                        logger.warning(f"[BM25-WORKER] Failed to add chunk {chunk_id}: {e}")

            # Commit to Tantivy (keeps writer open for next batch)
            self._writer.commit()

            # Mark papers as BM25 indexed in SQLite
            marked = self.paper_store.mark_bm25_indexed(paper_ids)

            # Update metrics
            elapsed = time.perf_counter() - start_time
            with self._lock:
                self.papers_indexed += len(batch)
                self.chunks_indexed += chunks_added
                self.commit_count += 1

            cps = chunks_added / elapsed if elapsed > 0 else 0
            logger.info(
                f"[BM25-WORKER] Committed batch: {len(batch)} papers, "
                f"{chunks_added} chunks in {elapsed:.2f}s ({cps:.0f} chunks/sec), "
                f"marked={marked}"
            )

        except Exception as e:
            logger.error(
                f"[BM25-WORKER] Failed to flush batch of {len(batch)} papers: {e}",
                exc_info=True
            )
            # Don't mark as indexed - will be retried on resume
            # NOTE: On fatal writer error, we may need to re-acquire the writer
            if "LockBusy" in str(e) or "writer" in str(e).lower():
                logger.warning("[BM25-WORKER] Writer may be corrupted, attempting recovery...")
                try:
                    self._release_writer()
                    time.sleep(1)  # Brief pause before re-acquiring
                    self._acquire_writer()
                except Exception as recovery_err:
                    logger.error(f"[BM25-WORKER] Writer recovery failed: {recovery_err}")

    def shutdown(self):
        """Signal the worker to stop."""
        self._shutdown.set()

    def get_metrics(self) -> dict:
        """Get current metrics snapshot."""
        with self._lock:
            return {
                "papers_indexed": self.papers_indexed,
                "chunks_indexed": self.chunks_indexed,
                "commit_count": self.commit_count,
            }
