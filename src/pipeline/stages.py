"""
Concrete pipeline stages for the streaming architecture.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import Iterator, Set, List, Optional
from pathlib import Path

from .streaming import PipelineStage, PipelineItem
from ..storage.paper_store import PaperStore, DiscoveredPaper
from ..acquisition.paper_downloader import PaperDownloader

logger = logging.getLogger(__name__)

from threading import Event

class DatabaseSource:
    """
    Yields pending papers from the database.
    Acts as the source of the pipeline stream.
    Supports continuous polling for concurrent discovery.
    """
    def __init__(self, paper_store: PaperStore, batch_size: int = 100, continuous: bool = False,
                 stop_signal: Optional[Event] = None, target_status: Optional[str] = None,
                 source_filter: Optional[str] = None, path_filter: Optional[str] = None):
        self.paper_store = paper_store
        self.batch_size = batch_size
        self.continuous = continuous
        self.stop_signal = stop_signal
        self.target_status = target_status
        self.source_filter = source_filter
        self.path_filter = path_filter  # NEW: filter by PDF path (for manual import)
        
        # Track seen IDs for non-discovered stages (low volume)
        self.seen_ids: Set[str] = set()
        
        # Cursor for tracking progress in the 'discovered' queue
        # Optimization: Start from the first 'discovered' paper ID, not 0.
        # This prevents scanning 300k+ "embedded" rows on restart.
        min_id = self.paper_store.get_min_id_for_status('discovered')
        self.last_discovered_id = max(0, min_id - 1) 
        
    def stream(self) -> Iterator[PipelineItem]:
        """
        Yields PipelineItems for papers that need processing.
        """
        poll_count = 0
        total_yielded = 0
        logger.info(f"[SOURCE] Starting stream | target_status={self.target_status}, "
                     f"batch_size={self.batch_size}, continuous={self.continuous}, "
                     f"stop_signal={'set' if self.stop_signal and self.stop_signal.is_set() else 'not_set'}")
        
        while True:
            poll_count += 1
            items_yielded = 0
            
            if self.target_status == 'discovered':
                # --- [PHASE 5] PRIORITY 1: Clear downloaded backlog first ---
                # Avoids stalling GPU while waiting for new downloads if work is already on disk
                backlog_ids = self._get_pending_ids("downloaded", limit=1000)
                if backlog_ids:
                    logger.info(f"[SOURCE] Found {len(backlog_ids)} 'downloaded' papers in backlog. Yielding first.")
                    for uid in backlog_ids:
                        if uid in self.seen_ids: continue
                        paper = self.paper_store.get_paper(uid)
                        if paper:
                            self.seen_ids.add(uid)
                            items_yielded += 1
                            yield PipelineItem(id=uid, payload=paper)
                    
                    if items_yielded >= self.batch_size:
                        continue # Re-poll downloaded backlog
                
                # --- [PHASE 5] PRIORITY 2: New discovered work ---
                new_papers = self.paper_store.get_newest_discovered_papers(
                    limit=max(1, self.batch_size - items_yielded)
                )
                logger.info(f"[SOURCE] Poll #{poll_count} | fetched={len(new_papers)} discovered papers")
                
                for row_id, paper in new_papers:
                    if paper.unique_id in self.seen_ids:
                        continue
                    self.seen_ids.add(paper.unique_id)
                    items_yielded += 1
                    yield PipelineItem(id=paper.unique_id, payload=paper)
                    
                    if self.stop_signal and self.stop_signal.is_set():
                        logger.info("[SOURCE] Stop signal during discovered batch.")
                        return

            elif self.target_status == 'downloaded':
                # Polling Approach for Download -> Embed
                # Since items move out of 'downloaded' status (to 'chunked'/'embedded'),
                # we don't use a monotonic cursor ID, but rather query for currently valid items.
                ids = self._get_pending_ids("downloaded", limit=self.batch_size)
                skipped_seen = 0
                skipped_none = 0
                
                for uid in ids:
                    # Basic deduplication for current run, though status change handles most
                    if uid in self.seen_ids:
                        skipped_seen += 1
                        continue
                        
                    paper = self.paper_store.get_paper(uid)
                    if paper:
                        self.seen_ids.add(uid)
                        items_yielded += 1
                        yield PipelineItem(id=paper.unique_id, payload=paper)
                    else:
                        skipped_none += 1
                        logger.warning(f"[SOURCE] get_paper returned None for uid={uid}")
                
                logger.info(f"[SOURCE] Poll #{poll_count} | query_returned={len(ids)}, "
                            f"yielded={items_yielded}, skipped_seen={skipped_seen}, "
                            f"skipped_none={skipped_none}, seen_ids_size={len(self.seen_ids)}, "
                            f"total_yielded={total_yielded + items_yielded}")
                        
            else:
                # Legacy Mixed Mode (Fallback)
                # 1. Fetch Discovered
                new_papers = self.paper_store.get_discovered_papers_since(
                    self.last_discovered_id, 
                    limit=self.batch_size
                )
                for row_id, paper in new_papers:
                    self.last_discovered_id = row_id
                    items_yielded += 1
                    yield PipelineItem(id=paper.unique_id, payload=paper)
                    # Check stop signal between each item (Phase 3 fix)
                    if self.stop_signal and self.stop_signal.is_set():
                        logger.info(f"Source ({self.target_status}) stop signal during discovered batch.")
                        return
                
                # 2. Fetch Downloaded
                ids = self._get_pending_ids("downloaded", limit=self.batch_size)
                for uid in ids:
                    if uid in self.seen_ids: continue
                    paper = self.paper_store.get_paper(uid)
                    if paper:
                        self.seen_ids.add(uid)
                        items_yielded += 1
                        yield PipelineItem(id=paper.unique_id, payload=paper)
                        # Check stop signal between each item (Phase 3 fix)
                        if self.stop_signal and self.stop_signal.is_set():
                            logger.info(f"Source ({self.target_status}) stop signal during downloaded batch.")
                            return

            total_yielded += items_yielded

            if items_yielded == 0:
                if not self.continuous:
                    logger.info(f"[SOURCE] Non-continuous mode: backlog exhausted after #{poll_count} polls. Terminating. | total_yielded={total_yielded}")
                    break
                
                # If we found nothing new, check if we should stop
                if self.stop_signal and self.stop_signal.is_set():
                    logger.info(f"[SOURCE] Stop signal received after empty poll #{poll_count} | total_yielded={total_yielded}")
                    break
                
                logger.debug(f"[SOURCE] Empty poll #{poll_count}, sleeping 2s | stop_signal_set={self.stop_signal.is_set() if self.stop_signal else 'N/A'}")
                # Sleep briefly
                time.sleep(2.0)
        
        logger.info(f"[SOURCE] Stream ended | polls={poll_count}, total_yielded={total_yielded}, seen_ids={len(self.seen_ids)}")
            
    def _get_pending_ids(self, status: str, limit: int = 100) -> List[str]:
        # Helper to get pending IDs with limit
        # Build query dynamically based on filters
        query = "SELECT unique_id FROM papers WHERE status = ?"
        params = [status]

        if self.source_filter:
            query += " AND source = ?"
            params.append(self.source_filter)

        # NEW: Add path filter for manual import directory
        if self.path_filter:
            query += " AND pdf_path LIKE ?"
            params.append(f"{self.path_filter}%")

        query += " LIMIT ?"
        params.append(limit)

        with self.paper_store.db.get_connection() as conn:
            return [r[0] for r in conn.execute(query, params).fetchall()]

class DownloadStage(PipelineStage):
    """
    Concurrent download stage using ThreadPoolExecutor.
    """
    def __init__(self, downloader: PaperDownloader, paper_store: PaperStore, max_workers: int = 4):
        super().__init__("Download")
        self.downloader = downloader
        self.paper_store = paper_store
        self.max_workers = max_workers
        
    def process(self, input_stream: Iterator[PipelineItem]) -> Iterator[PipelineItem]:
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            pending_futures = {} # Future -> PipelineItem
            
            # Helper to drain completed futures
            def yield_completed(wait_futures, pending_map):
                done, _ = wait(wait_futures, return_when=FIRST_COMPLETED)
                for f in done:
                    item = pending_map.pop(f)
                    try:
                        result = f.result() # This is DownloadResult from helper wrapper
                        # Update Item
                        paper: DiscoveredPaper = item.payload
                        if result['success']:
                            # Update Paper object in payload
                            paper.status = "downloaded"
                            paper.pdf_path = result['path']
                            
                            # Persist to DB immediately (Checkpoint)
                            self.paper_store.update_status(paper.unique_id, "downloaded", pdf_path=result['path'])
                            logger.info(f"Downloaded: {paper.unique_id}")
                        else:
                            item.fail(f"Download failed: {result['error']}")
                            # Update DB
                            self.paper_store.update_status(paper.unique_id, "failed_download", error=result['error'])
                            
                    except Exception as e:
                        self._handle_error(item, e)
                    
                    yield item
                return done # Returned futures to remove from set
            
            for item in input_stream:
                if not item.is_valid:
                    yield item
                    continue
                
                paper: DiscoveredPaper = item.payload
                
                # Check if already downloaded (Passthrough)
                if paper.status != "discovered":
                     # If status is 'downloaded' or 'chunked' etc, we pass it through
                     # (Assuming strict ordering: Source yields pending items)
                     yield item
                     continue
                
                # Submit download task
                future = executor.submit(self._download_wrapper, paper)
                pending_futures[future] = item
                
                # Backpressure: If too many workers, wait
                if len(pending_futures) >= self.max_workers:
                    done_futures = yield from yield_completed(pending_futures.keys(), pending_futures)
                    
            # Drain remaining
            while pending_futures:
                yield from yield_completed(pending_futures.keys(), pending_futures)
                
    def _download_wrapper(self, paper: DiscoveredPaper) -> dict:
        """Helper to run in thread."""
        # PaperDownloader.download_with_cascade returns DownloadResult
        result = self.downloader.download_with_cascade(paper)
        return {
            'success': result.success,
            'path': str(result.file_path) if result.file_path else None,
            'error': result.error
        }

class ChunkStage(PipelineStage):
    """
    Parses PDF and splits into chunks.
    Refactored to yield atomic Paper items (List[Chunk]).
    """
    def __init__(self, parser_func, chunker_func, paper_store: PaperStore):
        super().__init__("Chunk")
        self.parser = parser_func
        self.chunker = chunker_func
        self.paper_store = paper_store
    
    def process(self, input_stream: Iterator[PipelineItem]) -> Iterator[PipelineItem]:
        for item in input_stream:
            if not item.is_valid:
                logger.warning(f"[CHUNK-SKIP] Skipping invalid item: id={item.id}, error={item.error}")
                yield item
                continue
                
            paper: DiscoveredPaper = item.payload
            
            # Passthrough if already embedded (fully done) - though DBSource shouldn't yield these
            if paper.status == "embedded":
                logger.info(f"[CHUNK-SKIP] Paper={paper.unique_id} already embedded, passing through")
                yield item
                continue

            # Diagnostic logging - START
            logger.debug(f"[CHUNK-START] Paper={paper.unique_id}, Title='{paper.title[:50]}...', PDF={paper.pdf_path}")

            try:
                # 1. Parse PDF
                if not paper.pdf_path or not Path(paper.pdf_path).exists():
                    logger.error(f"[CHUNK-ERROR] Paper={paper.unique_id}, PDF not found: {paper.pdf_path}")
                    item.fail(f"PDF not found: {paper.pdf_path}")
                    self.paper_store.update_status(paper.unique_id, "failed_parse", error="PDF not found")
                    yield item
                    continue
                
                logger.debug(f"[CHUNK-PARSE] Parsing PDF: {paper.pdf_path}")
                text_content = self.parser(paper.pdf_path)
                
                # Fix 2.2: Zombie Paper Handling
                if not text_content:
                    logger.error(f"[CHUNK-ERROR] Paper={paper.unique_id}, Empty text extracted")
                    item.fail("Empty text extracted")
                    self.paper_store.update_status(paper.unique_id, "failed_empty", error="Empty text")
                    yield item # Yield failed item to drain pipe
                    continue
                
                # Log extracted content size (text_content may be Document or string)
                content_len = len(text_content.full_text) if hasattr(text_content, 'full_text') else len(str(text_content))
                logger.debug(f"[CHUNK-PARSE] Extracted {content_len} characters")
                     
                # 2. Chunk
                chunks = self.chunker(text_content)
                
                # [NEW] Use pre-calculated APA from Discovery
                apa_ref = paper.apa_reference
                
                # Fallback if missing (e.g. legacy paper not fully backfilled in memory, though DB has it)
                if not apa_ref:
                     # This might happen if DBSource yielded a paper without apa_ref populated in object
                     # But PaperStore._row_to_paper now populates it.
                     apa_ref = "Reference unavailable"

                # Inject into Chunks
                for i, chunk in enumerate(chunks):
                    # Ensure minimal metadata is present
                    chunk.metadata.update({
                        "title": paper.title,
                        "authors": paper.authors,
                        "year": paper.year,
                        "venue": paper.venue,
                        "citation_count": paper.citation_count,
                        "apa_reference": apa_ref,
                        "doi": paper.doi
                    })
                    # Explicitly set DOI on chunk object if supported
                    if hasattr(chunk, 'doi'):
                        chunk.doi = paper.doi
                    if hasattr(chunk, 'metadata'):
                        chunk.metadata['doi'] = paper.doi
                
                # Fix 2.2: Zero Chunks Check
                if not chunks or len(chunks) == 0:
                    logger.error(f"[CHUNK-ERROR] Paper={paper.unique_id}, No chunks generated")
                    item.fail("No chunks generated")
                    self.paper_store.update_status(paper.unique_id, "failed_empty", error="No chunks")
                    yield item
                    continue
                
                # Payload transformation: Paper -> List[Chunk]
                # We put the paper in metadata so we don't lose it
                item.metadata['paper'] = paper
                item.payload = chunks 
                
                # We update status to 'chunked' (checkpoint)
                # But we do NOT yield multiple items. One item = One Paper.
                self.paper_store.update_status(paper.unique_id, "chunked") 
                
                logger.info(f"[CHUNK-COMPLETE] Paper={paper.unique_id}, Chunks={len(chunks)}, Status='chunked'")
                
                yield item
                
            except Exception as e:
                logger.error(f"[CHUNK-FAILED] Paper={paper.unique_id}, Error={e}", exc_info=True)
                self._handle_error(item, e)
                yield item

class EmbedStage(PipelineStage):
    """
    Embeds batches on GPU.
    Refactored to pass all texts to embedder for Smart Batching optimization.
    """
    def __init__(self, embedder):
        super().__init__("Embed")
        self.embedder = embedder
        # Note: mini_batch_size removed - embedder.batch_size controls GPU batching
        
    def process(self, input_stream: Iterator[PipelineItem]) -> Iterator[PipelineItem]:
        import time
        
        for item in input_stream:
            if not item.is_valid:
                logger.warning(f"[EMBED-SKIP] Skipping invalid item: id={item.id}, error={item.error}")
                yield item
                continue
            
            # Payload is List[Chunk] (Whole Paper)
            chunks = item.payload
            paper = item.metadata.get('paper')
            paper_id = paper.unique_id if paper else "UNKNOWN"
            
            # Sanity check
            if not isinstance(chunks, list) or not chunks:
                logger.warning(f"[EMBED-SKIP] Paper={paper_id} has no chunks to embed")
                yield item
                continue
            
            # Diagnostic logging - START
            total_chunks = len(chunks)
            logger.debug(f"[EMBED-START] Paper={paper_id}, Chunks={total_chunks}, embedder.batch_size={self.embedder.batch_size}")
            start_time = time.time()

            try:
                # Extract texts for embedding
                texts = [c.text for c in chunks]
                
                # SMART BATCHING: Pass ALL texts at once
                # sentence-transformers will sort by length to minimize padding
                # and batch according to embedder.batch_size
                logger.debug(f"[EMBED-PROCESS] Embedding {total_chunks} texts with Smart Batching...")
                all_vectors = self.embedder.embed(texts)
                
                # Log embedding dimension
                if all_vectors and len(all_vectors) > 0:
                    logger.info(f"[EMBED-DIM] Embedding dimension={len(all_vectors[0])}")
                
                # Validate vector count
                if len(all_vectors) != total_chunks:
                    logger.error(f"[EMBED-MISMATCH] Paper={paper_id}: {len(all_vectors)} vectors for {total_chunks} chunks!")
                    raise ValueError(f"Embedding mismatch: {len(all_vectors)} vectors for {total_chunks} chunks")
                
                # Assign vectors to chunks
                for chunk, vector in zip(chunks, all_vectors):
                    chunk.embedding = vector
                
                elapsed = time.time() - start_time
                chunks_per_sec = total_chunks / elapsed if elapsed > 0 else 0
                logger.info(f"[EMBED-COMPLETE] Paper={paper_id}, Chunks={total_chunks}, Time={elapsed:.2f}s, Speed={chunks_per_sec:.1f} chunks/sec")
                
                # Verify embeddings were assigned
                null_count = sum(1 for c in chunks if c.embedding is None)
                if null_count > 0:
                    logger.error(f"[EMBED-VERIFY] Paper={paper_id}: {null_count} chunks still have NULL embeddings after processing!")
                
                # Payload remains List[Chunk] (now enriched)
                yield item
                
            except Exception as e:
                logger.error(f"[EMBED-FAILED] Paper={paper_id}, Error={e}", exc_info=True)
                self._handle_error(item, e)
                yield item

class StorageStage(PipelineStage):
    """
    Saves embeddings to Vector Store and updates status.
    Refactored for Atomic Commit (Upsert All -> Update Status).
    """
    def __init__(self, vector_store, paper_store: PaperStore, status_notify_url: Optional[str] = None):
        super().__init__("Storage")
        self.vector_store = vector_store
        self.paper_store = paper_store
        # Hooks for metrics aggregation (injected by main script)
        self.on_success = None
        # URL for dashboard webhook to notify document completion
        self.status_notify_url = status_notify_url or "http://sme_dashboard_backend:8400/api/documents/internal/notify-completion"

    def _notify_dashboard(self, document_id: str, status: str, bm25_indexed: bool = False):
        """Notify dashboard backend of document completion for WebSocket broadcast."""
        try:
            import httpx
            response = httpx.post(
                self.status_notify_url,
                json={"document_id": document_id, "status": status, "bm25_indexed": bm25_indexed},
                timeout=2.0
            )
            if response.status_code == 200:
                logger.debug(f"[STORAGE-NOTIFY] Dashboard notified: {document_id} -> {status}")
            else:
                logger.warning(f"[STORAGE-NOTIFY] Dashboard notification failed: {response.status_code}")
        except Exception as e:
            logger.debug(f"[STORAGE-NOTIFY] Dashboard notification skipped: {e}")

    def process(self, input_stream: Iterator[PipelineItem]) -> Iterator[PipelineItem]:
        for item in input_stream:
            if not item.is_valid:
                logger.warning(f"[STORAGE-SKIP] Skipping invalid item: id={item.id}, error={item.error}")
                continue # End of line for failed items
                
            chunks = item.payload # List[Chunk] with embeddings
            paper = item.metadata.get('paper')
            
            if not paper:
                logger.error(f"[STORAGE-ERROR] Missing paper metadata for Item {item.id}")
                continue

            # Diagnostic logging - START
            logger.debug(f"[STORAGE-START] Paper={paper.unique_id}, Title='{paper.title[:50]}...', Chunks={len(chunks)}")
            
            # Validate embeddings before upsert
            null_embeddings = sum(1 for c in chunks if c.embedding is None)
            if null_embeddings > 0:
                logger.error(f"[STORAGE-ERROR] Paper={paper.unique_id} has {null_embeddings}/{len(chunks)} chunks with NULL embeddings!")
            
            # Sample embedding dimension check
            if chunks and chunks[0].embedding:
                logger.debug(f"[STORAGE-SAMPLE] First chunk embedding_dim={len(chunks[0].embedding)}")

            try:
                # 1. Upsert to Qdrant (Fix 2.10)
                logger.debug(f"[STORAGE-UPSERT] Calling vector_store.upsert() for {len(chunks)} chunks...")
                self.vector_store.upsert(chunks)
                logger.debug(f"[STORAGE-UPSERT] vector_store.upsert() completed successfully")
                
                # 2. Atomic Status Update (Fix 2.1)
                # Only AFTER all chunks are safely in Qdrant do we mark 'embedded'.
                logger.debug(f"[STORAGE-STATUS] Updating paper status to 'embedded'...")
                self.paper_store.update_status(paper.unique_id, "embedded")
                logger.info(f"[STORAGE-COMPLETE] Paper={paper.unique_id} successfully embedded and saved!")

                # 2.5. Notify dashboard of completion for real-time UI updates
                self._notify_dashboard(paper.unique_id, "ready")

                # 3. Metric Hook (Fix 2.6)
                if self.on_success:
                    self.on_success(paper, len(chunks))
                    
            except Exception as e:
                error_str = str(e)
                
                # Check for VectorStruct error - indicates corrupted state from interrupted run
                if "VectorStruct" in error_str:
                    logger.warning(f"[STORAGE-RESET] Paper={paper.unique_id} has corrupted embedding state. Resetting to 'downloaded' for full re-processing.")
                    self.paper_store.update_status(paper.unique_id, "downloaded", error=f"VectorStruct error - queued for re-processing: {error_str[:200]}")
                    self._handle_error(item, e)
                else:
                    logger.error(f"[STORAGE-FAILED] Paper={paper.unique_id}, Error={e}", exc_info=True)
                    self._handle_error(item, e)
                    # If storage fails for other reasons, mark as failed
                    self.paper_store.update_status(paper.unique_id, "failed_storage", error=error_str)
            
            yield item

