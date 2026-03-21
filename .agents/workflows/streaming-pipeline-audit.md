---
description: How to audit the streaming pipeline execution flow (autonomous_update.py --stream)
---

# Streaming Pipeline Audit Workflow

This workflow traces the complete execution of `docker exec sme_app python scripts/autonomous_update.py --stream` from Docker exec to final Qdrant upsert.

## Pre-requisites
- Access to the SME project codebase at `c:\gpt\SME`
- Understanding of Python threading, SQLite, and Qdrant

---

## Phase 1: Trace the Import Chain

1. Open `scripts/autonomous_update.py` and list all imports
2. For each import, read the source file's `__init__` or factory function
3. Document the dependency graph:
   ```
   autonomous_update.py
   ├── helpers.py → load_config (lru_cached)
   ├── db.py → DatabaseManager (SQLite + WAL)
   ├── paper_store.py → PaperStore (CRUD for papers)
   ├── paper_downloader.py → PaperDownloader (HTTP downloads)
   ├── loader.py → load_rag_pipeline_core (⚠️ loads ALL RAG components)
   ├── stages.py → DatabaseSource, DownloadStage, ChunkStage, EmbedStage, StorageStage
   ├── concurrent_pipeline.py → ConcurrentPipeline (threading + queues)
   ├── dead_letter_queue.py → DeadLetterQueue (SQLite-backed)
   ├── monitor.py → PipelineMonitor (heartbeat + metrics)
   ├── pdf_parser.py → PyMuPDFParser
   └── chunker.py → HierarchicalChunker
   ```

## Phase 2: Trace Startup Sequence (line by line)

4. **Config loading**: Verify `load_config` path and caching behavior
5. **Database init**: Check db_path extraction logic, WAL mode setup
6. **PDF cleanup**: Verify unique_id format matches between filename and DB
7. **Model loading**: Check what `load_rag_pipeline_core()` loads vs what pipeline needs
8. **Auto-tuner**: Check if `run_startup_optimization()` is called more than once
9. **Monitor init**: Verify all methods called on PipelineMonitor actually exist

## Phase 3: Trace Runtime Flow

10. **DatabaseSource.stream()**: Check stop_signal handling in each branch (discovered, downloaded, legacy)
11. **DownloadStage.process()**: Check ThreadPoolExecutor backpressure, error handling
12. **ConcurrentPipeline.run()**: Check queue sizes, sentinel propagation, shutdown coordination
13. **_chunk_worker**: Check RetryPolicy usage, DLQ push on failure
14. **_embed_worker**: Check batch assembly, GPU batching, vector validation
15. **_store_worker**: Check upsert retry, on_success callback, VectorStruct recovery

## Phase 4: Check Shutdown Path

16. **SIGTERM handler**: Verify it sets BOTH stop_event AND pipeline._shutdown
17. **Sentinel propagation**: Verify chunk→embed→store sentinel chain
18. **Thread join timeouts**: Check if 10s is enough for in-flight operations
19. **Monitor.stop()**: Verify heartbeat thread cleanup

## Phase 5: Check for Silent Failures

20. Look for `except Exception: pass` patterns
21. Look for functions that return None on failure without logging
22. Look for status checks that compare wrong formats (e.g., filename vs unique_id)
23. Look for `@lru_cache` or global state that could serve stale data
24. Look for methods called that don't exist on the target class

## Phase 6: Check for Bottlenecks

25. **I/O bound**: SQLite queries per paper (count them in the full flow)
26. **CPU bound**: PDF parsing parallelism (ThreadPoolExecutor workers)
27. **GPU bound**: Embedding batch size vs available VRAM
28. **Network bound**: Qdrant upsert latency, Ollama embedding latency
29. **Queue pressure**: Q1 (parsed→embed) and Q2 (embed→store) sizes vs throughput ratios

## Phase 7: Document Findings

30. Categorize by severity: CRITICAL / SEVERE / MODERATE / LOW
31. For each finding, document: file, line, root cause, impact, fix
32. Create a summary table with fix priority
33. Save to `pipeline_audit.md` artifact

---

## Known Issue Checklist

When running this audit, specifically check for these known problem patterns:

- [ ] `monitor.start_phase()` — does it exist?
- [ ] `run_startup_optimization()` — called more than once?
- [ ] PDF cleanup — filename-to-unique_id format match?
- [ ] `load_rag_pipeline_core()` — loads unnecessary models?
- [ ] `stop_signal` — checked in all DatabaseSource branches?
- [ ] Re-processing — papers re-yielded before status changes?
- [ ] `StorageStage.on_success` + `ConcurrentPipeline.on_success` — double fire?
- [ ] Daemon threads — can they die mid-upsert?
