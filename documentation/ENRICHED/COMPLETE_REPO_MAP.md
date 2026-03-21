# COMPLETE REPOSITORY & DATA MODEL MAP
> **Notice to AI Agents:** This document is your zero-context handover blueprint. Use it to instantly locate any database schema, prompt logic, API endpoint, or pipeline orchestrator **without** spending context tokens searching the directory tree.

## 1. Directory Anatomy & Script Responsibilities
### `/app` Namespace
#### Directory: `app`
- **`main.py`**
  - *Purpose:* SME Research Assistant - Streamlit Chat Application
  - *Classes Defined:* None
  - *Global Functions:* init_session_state, check_auth, check_clarification_needed, load_rag_pipeline, process_query...

#### Directory: `app\components`
- **`__init__.py`**
  - *Purpose:* Components Package.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`progress_display.py`**
  - *Purpose:* Progress Display Components.
  - *Classes Defined:* None
  - *Global Functions:* render_status_block, render_progress_steps, render_progress_block
- **`rag_wrapper.py`**
  - *Purpose:* RAG Pipeline Wrappers.
  - *Classes Defined:* RetrieverWrapper(2 methods), RAGWrapper(3 methods)
  - *Global Functions:* None
- **`sidebar.py`**
  - *Purpose:* Sidebar Component.
  - *Classes Defined:* None
  - *Global Functions:* render_custom_header, render_custom_footer, render_divider, render_sidebar
- **`sidebar_config.py`**
  - *Purpose:* Sidebar Configuration Dataclass.
  - *Classes Defined:* SidebarConfig(0 methods)
  - *Global Functions:* None
- **`sidebar_styles.py`**
  - *Purpose:* Sidebar Styles Module.
  - *Classes Defined:* None
  - *Global Functions:* get_disabled_slider_css
- **`theme.py`**
  - *Purpose:* Theme Constants Module.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`welcome_screen.py`**
  - *Purpose:* Welcome Screen Component.
  - *Classes Defined:* None
  - *Global Functions:* get_indexed_papers_count, render_welcome_screen, get_welcome_screen_html

#### Directory: `app\state`
- **`__init__.py`**
  - *Purpose:* Centralized Session State Manager.
  - *Classes Defined:* StateDefaults(0 methods), SessionManager(11 methods)
  - *Global Functions:* None

#### Directory: `app\styles`
- **`__init__.py`**
  - *Purpose:* Style Injection Module.
  - *Classes Defined:* None
  - *Global Functions:* inject_theme_css, inject_monitor_css, inject_processing_overlay, remove_processing_overlay

#### Directory: `app\utils`
- **`video_helpers.py`**
  - *Purpose:* Helper utilities for injecting complex UI components like streaming local video.
  - *Classes Defined:* None
  - *Global Functions:* get_base64_video, inject_animated_video

### `/config` Namespace
### `/dashboard` Namespace
#### Directory: `dashboard\backend`
- **`audit_logger.py`**
  - *Purpose:* SME Dashboard — Audit Logger
  - *Classes Defined:* None
  - *Global Functions:* log_audit, read_audit
- **`auth.py`**
  - *Purpose:* SME Dashboard — JWT Authentication & Role-Based Access Control
  - *Classes Defined:* User(0 methods), TokenPayload(0 methods), LoginRequest(0 methods), TokenResponse(0 methods)
  - *Global Functions:* _load_users, _save_users, create_user, _create_token, create_access_token...
- **`command_runner.py`**
  - *Purpose:* SME Dashboard — Pipeline Command Runner
  - *Classes Defined:* PipelineProcessTracker(4 methods)
  - *Global Functions:* None
- **`config_manager.py`**
  - *Purpose:* SME Dashboard — YAML Config Manager
  - *Classes Defined:* None
  - *Global Functions:* compute_etag, read_config, validate_config, save_config, list_versions...
- **`db_reader.py`**
  - *Purpose:* SME Dashboard — SQLite Database Reader
  - *Classes Defined:* None
  - *Global Functions:* _connect, _query_with_retry, _refresher_loop, increment_count, get_paper_counts...
- **`main.py`**
  - *Purpose:* SME Pipeline Dashboard — FastAPI Backend
  - *Classes Defined:* None
  - *Global Functions:* None
- **`metrics_collector.py`**
  - *Purpose:* SME Dashboard — System Metrics Collector
  - *Classes Defined:* MetricsCollector(0 methods)
  - *Global Functions:* None
- **`prometheus_metrics.py`**
  - *Purpose:* SME Dashboard — Prometheus Metrics Middleware
  - *Classes Defined:* None
  - *Global Functions:* metrics_endpoint, update_pipeline_gauge, update_ws_clients_gauge, update_qdrant_gauge, update_db_gauge...
- **`qdrant_client.py`**
  - *Purpose:* SME Dashboard — Qdrant Client
  - *Classes Defined:* None
  - *Global Functions:* _get_collection_size_gb
- **`rate_limiter.py`**
  - *Purpose:* SME Dashboard — Rate Limiting Middleware
  - *Classes Defined:* None
  - *Global Functions:* _clean_old
- **`ws_manager.py`**
  - *Purpose:* SME Dashboard — WebSocket Connection Manager
  - *Classes Defined:* WSManager(2 methods)
  - *Global Functions:* None

#### Directory: `dashboard\backend\routes`
- **`__init__.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`audit_routes.py`**
  - *Purpose:* Audit routes: read audit log with filters.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`auth_routes.py`**
  - *Purpose:* Auth routes: login, refresh, me, create-user.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`config_routes.py`**
  - *Purpose:* Config routes: read, validate, save, versions, revert.
  - *Classes Defined:* ValidateRequest(0 methods), SaveRequest(0 methods), RevertRequest(0 methods)
  - *Global Functions:* None
- **`db_routes.py`**
  - *Purpose:* Database routes: paper counts, coverage drilldown.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`dlq_routes.py`**
  - *Purpose:* DLQ routes: list, retry, skip.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`metrics_routes.py`**
  - *Purpose:* Metrics routes: system, projection, history, coverage.
  - *Classes Defined:* None
  - *Global Functions:* record_sample
- **`qdrant_routes.py`**
  - *Purpose:* Qdrant routes: stats, snapshot with safeguards.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`run_routes.py`**
  - *Purpose:* Run control routes: status, precheck, start, stop.
  - *Classes Defined:* StartRequest(0 methods), StopRequest(0 methods)
  - *Global Functions:* None
- **`ws_routes.py`**
  - *Purpose:* WebSocket route: real-time metrics, logs, events.
  - *Classes Defined:* None
  - *Global Functions:* set_ws_manager, _parse_log_line

#### Directory: `dashboard\backend\tests`
- **`conftest.py`**
  - *Purpose:* Shared test fixtures for the dashboard backend test suite.
  - *Classes Defined:* None
  - *Global Functions:* tmp_dir, config_file, users_file, setup_config_env, setup_auth_env
- **`test_auth.py`**
  - *Purpose:* Unit tests for auth.py — JWT tokens, RBAC, user management.
  - *Classes Defined:* TestUserManagement(6 methods), TestTokens(5 methods), TestRBAC(3 methods)
  - *Global Functions:* None
- **`test_command_runner.py`**
  - *Purpose:* Unit tests for command_runner.py — whitelisted commands, injection prevention.
  - *Classes Defined:* TestAllowedModes(9 methods), TestInjectionPrevention(4 methods), TestGracefulStopTimeout(1 methods)
  - *Global Functions:* None
- **`test_config_manager.py`**
  - *Purpose:* Unit tests for config_manager.py — validation, save, backup, revert.
  - *Classes Defined:* TestValidation(10 methods), TestETag(3 methods), TestSaveAndBackup(6 methods), TestListVersions(2 methods)
  - *Global Functions:* None
- **`test_integration.py`**
  - *Purpose:* Integration tests — test API endpoints via FastAPI TestClient.
  - *Classes Defined:* TestAuthEndpoints(6 methods), TestConfigEndpoints(6 methods), TestRBACEnforcement(9 methods)
  - *Global Functions:* client, _login

#### Directory: `dashboard\gpu_exporter`
- **`main.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* get_gpu_metrics, health

### `/scripts` Namespace
#### Directory: `scripts`
- **`analyze_metadata_coverage.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* analyze_coverage
- **`audit_apa.py`**
  - *Purpose:* Fast sampled audit of APA reference coverage in Qdrant.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`autonomous_update.py`**
  - *Purpose:* SME Autonomous Update Pipeline — Gold Standard
  - *Classes Defined:* None
  - *Global Functions:* _cleanup_embedded_pdfs, _discovery_worker, run_pipeline
- **`build_bm25_tantivy.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* main, get_dir_size
- **`check_chunked.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`check_cuda.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`check_gpu.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* check_env
- **`check_live_status.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* get_dir_size, check_live_status_deep, run_math
- **`check_qdrant_methods.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`check_query_signature.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`check_tantivy_index.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* main
- **`db_stats.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* inspect_db
- **`debug_embedder_memory.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* print_memory, check_quantization, main
- **`debug_pdf.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* debug_pdf
- **`debug_search.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* debug_search
- **`fast_ingest.py`**
  - *Purpose:* Fast GPU-optimized paper ingestion for SME RAG system.
  - *Classes Defined:* None
  - *Global Functions:* main
- **`full_ingest.py`**
  - *Purpose:* Full Scale Ingestion Script for SME RAG System (52k Papers).
  - *Classes Defined:* None
  - *Global Functions:* load_state, save_state, worker_parse_file, main, finalize_bm25
- **`full_ingest_optimized.py`**
  - *Purpose:* Optimized Full Scale Ingestion Script for SME RAG System (52k Papers).
  - *Classes Defined:* None
  - *Global Functions:* load_state, save_state, worker_parse_file, producer_task, consumer_task...
- **`ingest_papers.py`**
  - *Purpose:* SME Research Assistant - Paper Ingestion Script
  - *Classes Defined:* PaperIngester(2 methods)
  - *Global Functions:* main
- **`inspect_cross_encoder.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* print_memory
- **`migrate_cache.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* migrate_cache
- **`migrate_collection.py`**
  - *Purpose:* SME Collection Migration Script (v2 — streaming)
  - *Classes Defined:* None
  - *Global Functions:* stream_migrate, wait_for_index, main
- **`monitor_qdrant.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* monitor_progress
- **`monitor_resources.py`**
  - *Purpose:* Resource monitor for streaming pipeline diagnosis.
  - *Classes Defined:* None
  - *Global Functions:* get_memory_info, get_process_memory, get_pipeline_processes_memory, get_gpu_info, get_disk_io...
- **`monitor_status.py`**
  - *Purpose:* SME Pipeline Monitor
  - *Classes Defined:* SpeedTracker(2 methods), SpeedTracker(2 methods)
  - *Global Functions:* get_gpu_stats, get_db_stats, get_qdrant_count, main
- **`pipeline_api.py`**
  - *Purpose:* Internal API to control the SME pipeline process natively without Docker Exec.
  - *Classes Defined:* PipelineProcessTracker(10 methods), StartRequest(0 methods), StopRequest(0 methods)
  - *Global Functions:* status, start, stop
- **`remediate_failures.py`**
  - *Purpose:* Remediation Script for Failed PDF Ingestions.
  - *Classes Defined:* None
  - *Global Functions:* load_failures, check_ocr_availability, robust_parse, main
- **`stop_pipeline.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* stop_pipeline
- **`sync_db_from_files.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* normalize_unique_id, main
- **`test_extraction.py`**
  - *Purpose:* Quick test script for PDF extraction on sample papers.
  - *Classes Defined:* None
  - *Global Functions:* test_extraction
- **`test_heavy_startup.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* main
- **`test_pipeline.py`**
  - *Purpose:* Quick test of embedding and storage pipeline.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`test_search_syntax.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* test_search_syntax
- **`test_tantivy.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* test_tantivy_basic
- **`verify_4bit_simple.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* print_gpu_memory, main
- **`verify_canary.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* run_canary
- **`verify_embedder_fast.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* FastTransformerEmbedder(2 methods)
  - *Global Functions:* patched_load_model, print_gpu_memory, main
- **`verify_embedder_performance.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* print_gpu_memory, main
- **`verify_hybrid_tantivy.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* main
- **`verify_remote.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* main

### `/src` Namespace
#### Directory: `src`
- **`__init__.py`**
  - *Purpose:* SME Research Assistant - Source Package
  - *Classes Defined:* None
  - *Global Functions:* None

#### Directory: `src\academic_v2`
- **`__init__.py`**
  - *Purpose:* Academic Engine V2: Evidence-First Architecture.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`architect.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* Architect(8 methods)
  - *Global Functions:* None
- **`drafter.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* Drafter(3 methods)
  - *Global Functions:* None
- **`engine.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* AcademicEngine(4 methods)
  - *Global Functions:* None
- **`librarian.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* Librarian(7 methods)
  - *Global Functions:* None
- **`models.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* MethodologyType(0 methods), CertaintyLevel(0 methods), RhetoricalRole(3 methods), Methodology(0 methods), AtomicFact(0 methods), ParagraphPlan(0 methods)
  - *Global Functions:* None

#### Directory: `src\acquisition`
- **`__init__.py`**
  - *Purpose:* SME Research Assistant - Paper Acquisition Module
  - *Classes Defined:* None
  - *Global Functions:* None
- **`coverage_manager.py`**
  - *Purpose:* SME Research Assistant - Coverage Manager
  - *Classes Defined:* CoverageManager(7 methods)
  - *Global Functions:* None
- **`email_manager.py`**
  - *Purpose:* SME Research Assistant - Email Manager
  - *Classes Defined:* EmailStatus(0 methods), EmailRotator(8 methods)
  - *Global Functions:* None
- **`paper_discoverer.py`**
  - *Purpose:* SME Research Assistant - Paper Discoverer
  - *Classes Defined:* DiscoveredPaper(4 methods), PaperDiscoverer(15 methods)
  - *Global Functions:* None
- **`paper_downloader.py`**
  - *Purpose:* SME Research Assistant - Paper Downloader
  - *Classes Defined:* DownloadResult(0 methods), DownloadStats(1 methods), PaperDownloader(12 methods)
  - *Global Functions:* None

#### Directory: `src\acquisition\api_clients`
- **`__init__.py`**
  - *Purpose:* SME Research Assistant - API Clients for Paper Acquisition
  - *Classes Defined:* None
  - *Global Functions:* None
- **`arxiv_client.py`**
  - *Purpose:* SME Research Assistant - arXiv API Client
  - *Classes Defined:* ArxivPaperMetadata(1 methods), ArxivClient(10 methods)
  - *Global Functions:* None
- **`crossref.py`**
  - *Purpose:* SME Research Assistant - Crossref API Client
  - *Classes Defined:* CrossrefClient(7 methods)
  - *Global Functions:* None
- **`openalex.py`**
  - *Purpose:* SME Research Assistant - OpenAlex API Client
  - *Classes Defined:* PaperMetadata(1 methods), OpenAlexClient(15 methods)
  - *Global Functions:* None
- **`semantic_scholar.py`**
  - *Purpose:* SME Research Assistant - Semantic Scholar API Client
  - *Classes Defined:* S2PaperMetadata(1 methods), SemanticScholarClient(11 methods)
  - *Global Functions:* None
- **`unpaywall.py`**
  - *Purpose:* SME Research Assistant - Unpaywall API Client
  - *Classes Defined:* OpenAccessLocation(0 methods), UnpaywallClient(9 methods)
  - *Global Functions:* None

#### Directory: `src\acquisition\downloaders`
- **`__init__.py`**
  - *Purpose:* SME Research Assistant - Downloaders Package
  - *Classes Defined:* None
  - *Global Functions:* None
- **`arxiv_downloader.py`**
  - *Purpose:* SME Research Assistant - arXiv Paper Downloader
  - *Classes Defined:* ArxivDownloader(5 methods)
  - *Global Functions:* None
- **`openalex_content.py`**
  - *Purpose:* SME Research Assistant - OpenAlex Content API Downloader
  - *Classes Defined:* OpenAlexContentDownloader(5 methods)
  - *Global Functions:* None
- **`unpaywall_downloader.py`**
  - *Purpose:* SME Research Assistant - Unpaywall API Downloader
  - *Classes Defined:* UnpaywallDownloader(7 methods)
  - *Global Functions:* None

#### Directory: `src\config`
- **`depth_presets.py`**
  - *Purpose:* Depth Preset Configuration for Research Queries.
  - *Classes Defined:* None
  - *Global Functions:* get_depth_preset, get_depth_options, get_depth_descriptions, resolve_paper_target
- **`progress_config.py`**
  - *Purpose:* Progress Configuration for Live Monitoring UI.
  - *Classes Defined:* None
  - *Global Functions:* get_config_name, get_config, get_main_pill_key, calculate_progress, get_step_to_subpill_mapping
- **`thresholds.py`**
  - *Purpose:* Centralized Thresholds Configuration.
  - *Classes Defined:* None
  - *Global Functions:* get_confidence_level

#### Directory: `src\core`
- **`__init__.py`**
  - *Purpose:* SME Research Assistant - Core Module
  - *Classes Defined:* None
  - *Global Functions:* None
- **`exceptions.py`**
  - *Purpose:* SME Research Assistant - Custom Exceptions
  - *Classes Defined:* SMEBaseException(1 methods), IngestionError(0 methods), PDFExtractionError(0 methods), InvalidPDFError(0 methods), DuplicateDocumentError(0 methods), LowQualityExtractionError(0 methods), IndexingError(0 methods), EmbeddingError(0 methods), VectorStoreError(0 methods), VectorStoreConnectionError(0 methods), RetrievalError(0 methods), NoResultsError(0 methods), RerankerError(0 methods), GenerationError(0 methods), LLMConnectionError(0 methods), LLMTimeoutError(0 methods), LLMRateLimitError(0 methods), ContextTooLongError(0 methods), SecurityError(0 methods), AuthenticationError(0 methods), AuthorizationError(0 methods), InputValidationError(0 methods), CacheError(0 methods), CacheConnectionError(0 methods), ConfigurationError(0 methods), MissingConfigError(0 methods), CircuitOpenError(0 methods)
  - *Global Functions:* None
- **`interfaces.py`**
  - *Purpose:* SME Research Assistant - Core Interfaces
  - *Classes Defined:* Document(0 methods), Chunk(0 methods), RetrievalResult(0 methods), GenerationResult(0 methods), QueryContext(0 methods), DocumentParser(2 methods), TextChunker(1 methods), Embedder(2 methods), VectorStore(4 methods), KeywordIndex(2 methods), Reranker(1 methods), LLMClient(3 methods), Cache(4 methods), MetricsCollector(3 methods), SectionResult(0 methods)
  - *Global Functions:* None
- **`rate_limiter.py`**
  - *Purpose:* Rate limiting utilities with exponential backoff.
  - *Classes Defined:* RateLimitExceeded(0 methods), RateLimiter(4 methods)
  - *Global Functions:* with_rate_limit

#### Directory: `src\generation`
- **`__init__.py`**
  - *Purpose:* SME Research Assistant - Generation Module
  - *Classes Defined:* None
  - *Global Functions:* None
- **`citation_validator.py`**
  - *Purpose:* Citation Validator for SME RAG System (Phase 12b.3).
  - *Classes Defined:* ValidationResult(0 methods), CitationValidator(6 methods)
  - *Global Functions:* validate_response, get_compliance_badge
- **`ollama_client.py`**
  - *Purpose:* SME Research Assistant - Ollama Client
  - *Classes Defined:* OllamaClient(8 methods)
  - *Global Functions:* create_ollama_client
- **`prompts.py`**
  - *Purpose:* SME Research Assistant - Prompt Templates
  - *Classes Defined:* PromptBuilder(6 methods)
  - *Global Functions:* create_prompt_builder

#### Directory: `src\indexing`
- **`__init__.py`**
  - *Purpose:* SME Research Assistant - Indexing Module
  - *Classes Defined:* None
  - *Global Functions:* None
- **`benchmark.py`**
  - *Purpose:* SME Research Assistant — Qdrant Benchmark & Diagnostics CLI
  - *Classes Defined:* None
  - *Global Functions:* load_config, get_qdrant_client, log_system_resources, cmd_status, cmd_optimize...
- **`bm25_index.py`**
  - *Purpose:* SME Research Assistant - BM25 Index
  - *Classes Defined:* BM25Index(12 methods)
  - *Global Functions:* create_bm25_index
- **`bm25_tantivy.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* TantivyBM25Index(7 methods)
  - *Global Functions:* None
- **`embedder.py`**
  - *Purpose:* SME Research Assistant - Embedder Factory
  - *Classes Defined:* None
  - *Global Functions:* create_embedder
- **`embedder_local.py`**
  - *Purpose:* SME Research Assistant - Embedder
  - *Classes Defined:* QuantizedTransformer(1 methods), TransformerEmbedder(8 methods)
  - *Global Functions:* None
- **`embedder_remote.py`**
  - *Purpose:* SME Research Assistant - Remote Embedder
  - *Classes Defined:* GPUHealthMonitor(7 methods), RemoteEmbedder(12 methods)
  - *Global Functions:* _probe_gpu_vram_mb, _compute_optimal_batch
- **`qdrant_optimizer.py`**
  - *Purpose:* SME Research Assistant — Qdrant Auto-Tuning Optimizer
  - *Classes Defined:* None
  - *Global Functions:* probe_hardware, calculate_footprints, determine_tier, compute_optimal_m, compute_ef_construct...
- **`vector_store.py`**
  - *Purpose:* SME Research Assistant - Vector Store
  - *Classes Defined:* QdrantVectorStore(10 methods)
  - *Global Functions:* create_vector_store

#### Directory: `src\ingestion`
- **`__init__.py`**
  - *Purpose:* SME Research Assistant - Ingestion Module
  - *Classes Defined:* None
  - *Global Functions:* None
- **`chunker.py`**
  - *Purpose:* SME Research Assistant - Text Chunker
  - *Classes Defined:* HierarchicalChunker(15 methods)
  - *Global Functions:* create_chunker
- **`metadata_enricher.py`**
  - *Purpose:* Inline Metadata Enricher for SME RAG System.
  - *Classes Defined:* None
  - *Global Functions:* format_author_apa, format_apa_reference, fetch_metadata_from_openalex, enrich_batch_sync, find_unenriched_dois...
- **`pdf_parser.py`**
  - *Purpose:* SME Research Assistant - PDF Parser
  - *Classes Defined:* PyMuPDFParser(12 methods)
  - *Global Functions:* create_parser
- **`preprocessor.py`**
  - *Purpose:* SME Research Assistant - Text Preprocessor
  - *Classes Defined:* TextPreprocessor(7 methods)
  - *Global Functions:* create_preprocessor

#### Directory: `src\pipeline`
- **`__init__.py`**
  - *Purpose:* SME Pipeline Module - State management and monitoring for graceful stop-and-go.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`chunk_worker.py`**
  - *Purpose:* SME Research Assistant - Multi-Process Parsing Worker
  - *Classes Defined:* None
  - *Global Functions:* process_paper_to_chunks
- **`concurrent_pipeline.py`**
  - *Purpose:* SME Research Assistant - Concurrent Pipeline
  - *Classes Defined:* PipelineMetrics(2 methods), ConcurrentPipeline(6 methods)
  - *Global Functions:* _worker_parse_paper
- **`dead_letter_queue.py`**
  - *Purpose:* SME Research Assistant - Dead Letter Queue
  - *Classes Defined:* DeadLetterQueue(9 methods)
  - *Global Functions:* None
- **`gpu_tuner.py`**
  - *Purpose:* SME Research Assistant - GPU Tuner & Health Monitor
  - *Classes Defined:* GPUHealthMonitor(4 methods), AutoTuner(7 methods)
  - *Global Functions:* probe_gpu, recommend_parallel, startup_gpu_report, derive_startup_config
- **`loader.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* load_rag_pipeline_core
- **`monitor.py`**
  - *Purpose:* SME Research Assistant - Pipeline Monitoring System
  - *Classes Defined:* PipelinePhase(0 methods), PipelineStatus(0 methods), AlertSeverity(0 methods), DiscoveryMetrics(1 methods), DownloadMetrics(1 methods), ChunkingMetrics(1 methods), EmbeddingMetrics(1 methods), ResourceMetrics(1 methods), Alert(1 methods), PipelineMetrics(1 methods), AlertManager(4 methods), PipelineMonitor(19 methods)
  - *Global Functions:* None
- **`retry_policy.py`**
  - *Purpose:* SME Research Assistant - Retry Policy
  - *Classes Defined:* RetryExhausted(1 methods), RetryPolicy(2 methods)
  - *Global Functions:* None
- **`stages.py`**
  - *Purpose:* Concrete pipeline stages for the streaming architecture.
  - *Classes Defined:* DatabaseSource(3 methods), DownloadStage(3 methods), ChunkStage(2 methods), EmbedStage(2 methods), StorageStage(2 methods)
  - *Global Functions:* None
- **`state_manager.py`**
  - *Purpose:* SME Research Assistant - Pipeline State Manager
  - *Classes Defined:* PhaseState(2 methods), PipelineState(14 methods)
  - *Global Functions:* compute_config_hash
- **`streaming.py`**
  - *Purpose:* Core streaming pipeline interfaces and data structures.
  - *Classes Defined:* PipelineItem(2 methods), PipelineStage(3 methods)
  - *Global Functions:* None

#### Directory: `src\retrieval`
- **`__init__.py`**
  - *Purpose:* SME Research Assistant - Retrieval Module
  - *Classes Defined:* None
  - *Global Functions:* None
- **`adaptive_depth.py`**
  - *Purpose:* Adaptive Depth Controller for Sequential RAG.
  - *Classes Defined:* AdaptiveParams(0 methods)
  - *Global Functions:* get_adaptive_params, should_continue_searching, get_expanded_k_values
- **`clarification_analyzer.py`**
  - *Purpose:* Clarification Analyzer for Sequential RAG.
  - *Classes Defined:* ClarificationQuestion(0 methods), ClarificationAnalysis(0 methods)
  - *Global Functions:* analyze_for_clarification, _is_simple_query, _parse_clarification_response, build_refined_query
- **`confidence_scorer.py`**
  - *Purpose:* Confidence Scorer for Sequential RAG.
  - *Classes Defined:* ConfidenceScore(0 methods)
  - *Global Functions:* calculate_confidence, _extract_key_terms, should_skip_reflection, get_confidence_emoji
- **`context_builder.py`**
  - *Purpose:* SME Research Assistant - Context Builder
  - *Classes Defined:* ContextBuilder(9 methods)
  - *Global Functions:* create_context_builder
- **`entity_extractor.py`**
  - *Purpose:* Entity Extractor for Sequential RAG.
  - *Classes Defined:* ExtractedEntities(0 methods)
  - *Global Functions:* extract_entities, _extract_unique_matches, generate_targeted_queries, entities_to_display_string, get_coverage_score
- **`gap_analyzer.py`**
  - *Purpose:* Gap Analyzer for Sequential RAG.
  - *Classes Defined:* Gap(0 methods), GapAnalysis(0 methods)
  - *Global Functions:* analyze_gaps, _parse_gap_response, get_follow_up_queries, gaps_to_display_string
- **`hybrid_search.py`**
  - *Purpose:* SME Research Assistant - Hybrid Search
  - *Classes Defined:* HybridSearch(2 methods)
  - *Global Functions:* create_hybrid_search
- **`hyde.py`**
  - *Purpose:* HyDE (Hypothetical Document Embeddings) for improved semantic retrieval.
  - *Classes Defined:* HyDERetriever(3 methods)
  - *Global Functions:* create_hyde_retriever
- **`parallel_search.py`**
  - *Purpose:* Parallel Search Executor for Sequential RAG.
  - *Classes Defined:* SearchResult(0 methods), ParallelSearchExecutor(4 methods)
  - *Global Functions:* create_parallel_executor
- **`query_expander.py`**
  - *Purpose:* Query Expansion and Decomposition for complex research questions.
  - *Classes Defined:* QueryExpander(6 methods)
  - *Global Functions:* create_query_expander
- **`reranker.py`**
  - *Purpose:* SME Research Assistant - Reranker
  - *Classes Defined:* OllamaReranker(7 methods), CrossEncoderReranker(4 methods), NoOpReranker(1 methods)
  - *Global Functions:* create_reranker
- **`sequential_rag.py`**
  - *Purpose:* Sequential Thinking RAG.
  - *Classes Defined:* SequentialRAG(5 methods)
  - *Global Functions:* create_sequential_rag

#### Directory: `src\retrieval\sequential`
- **`__init__.py`**
  - *Purpose:* Sequential RAG Package.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`generation.py`**
  - *Purpose:* Generation Mixin for Sequential RAG.
  - *Classes Defined:* GenerationMixin(9 methods)
  - *Global Functions:* None
- **`models.py`**
  - *Purpose:* Data Models for Sequential RAG.
  - *Classes Defined:* SearchRound(0 methods), GenerationProgress(0 methods)
  - *Global Functions:* is_final_section
- **`planning.py`**
  - *Purpose:* Planning Mixin for Sequential RAG.
  - *Classes Defined:* PlanningMixin(7 methods)
  - *Global Functions:* None
- **`proofreading.py`**
  - *Purpose:* Proofreading Mixin for Sequential RAG.
  - *Classes Defined:* ProofreadingMixin(10 methods)
  - *Global Functions:* None
- **`reflection.py`**
  - *Purpose:* Reflection Mixin for Sequential RAG.
  - *Classes Defined:* ReflectionMixin(3 methods)
  - *Global Functions:* None
- **`search.py`**
  - *Purpose:* Search Mixin for Sequential RAG.
  - *Classes Defined:* SearchMixin(5 methods)
  - *Global Functions:* None

#### Directory: `src\security`
- **`__init__.py`**
  - *Purpose:* SME Research Assistant - Security Module
  - *Classes Defined:* None
  - *Global Functions:* None
- **`audit.py`**
  - *Purpose:* SME Research Assistant - Security: Audit Logger
  - *Classes Defined:* AuditEntry(0 methods), AuditLogger(10 methods)
  - *Global Functions:* get_audit_logger
- **`auth.py`**
  - *Purpose:* SME Research Assistant - Security: Authentication
  - *Classes Defined:* Session(0 methods), AuthManager(7 methods)
  - *Global Functions:* get_auth_manager
- **`sanitizer.py`**
  - *Purpose:* SME Research Assistant - Security: Input Sanitizer
  - *Classes Defined:* InputSanitizer(7 methods)
  - *Global Functions:* get_sanitizer

#### Directory: `src\storage`
- **`__init__.py`**
  - *Purpose:* SME Research Assistant - Storage Module
  - *Classes Defined:* None
  - *Global Functions:* None
- **`db.py`**
  - *Purpose:* SME Research Assistant - Database Manager
  - *Classes Defined:* DatabaseManager(4 methods)
  - *Global Functions:* None
- **`paper_store.py`**
  - *Purpose:* SME Research Assistant - Paper Store
  - *Classes Defined:* PaperStore(17 methods)
  - *Global Functions:* None
- **`schema.py`**
  - *Purpose:* SME Research Assistant - Database Schema
  - *Classes Defined:* None
  - *Global Functions:* None
- **`state_store.py`**
  - *Purpose:* SME Research Assistant - State Store
  - *Classes Defined:* StateStore(4 methods)
  - *Global Functions:* None

#### Directory: `src\ui`
- **`__init__.py`**
  - *Purpose:* No module docstring provided.
  - *Classes Defined:* None
  - *Global Functions:* None
- **`monitor_components.py`**
  - *Purpose:* Live Monitor Panel Components.
  - *Classes Defined:* MonitorStep(3 methods)
  - *Global Functions:* _get_session_state, _init_defaults, _get_state, _get_steps, _get_warnings...

#### Directory: `src\utils`
- **`__init__.py`**
  - *Purpose:* SME Research Assistant - Utilities Module
  - *Classes Defined:* None
  - *Global Functions:* None
- **`adaptive_tokens.py`**
  - *Purpose:* Adaptive Token Manager for RAG Pipeline.
  - *Classes Defined:* AdaptiveTokenManager(5 methods)
  - *Global Functions:* None
- **`apa_resolver.py`**
  - *Purpose:* SME Research Assistant - APA Reference Resolver
  - *Classes Defined:* APAReferenceResolver(4 methods)
  - *Global Functions:* create_apa_resolver
- **`citation_density.py`**
  - *Purpose:* Dynamic Citation Density Calculator for SME RAG System.
  - *Classes Defined:* None
  - *Global Functions:* assess_question_complexity, estimate_response_length, calculate_citation_target, generate_citation_instructions, get_citation_instructions
- **`diagnostics.py`**
  - *Purpose:* Diagnostic Utility for SME Research Assistant.
  - *Classes Defined:* DiagnosticGate(5 methods)
  - *Global Functions:* report_diagnostic
- **`feedback_logger.py`**
  - *Purpose:* User Feedback Logging for RAG responses.
  - *Classes Defined:* None
  - *Global Functions:* log_feedback, get_feedback_stats
- **`helpers.py`**
  - *Purpose:* SME Research Assistant - Utilities
  - *Classes Defined:* None
  - *Global Functions:* load_config, load_prompts, extract_doi_from_filename, generate_chunk_id, generate_content_hash...
- **`json_parser.py`**
  - *Purpose:* Centralized JSON parsing utility for LLM outputs.
  - *Classes Defined:* None
  - *Global Functions:* parse_llm_json, _repair_json_structure
- **`latency_tracer.py`**
  - *Purpose:* Latency Tracing for RAG Pipeline.
  - *Classes Defined:* TimingSpan(1 methods), LatencyTrace(4 methods), LatencyTracer(6 methods)
  - *Global Functions:* create_tracer
- **`latex_renderer.py`**
  - *Purpose:* LaTeX Equation Renderer for Streamlit.
  - *Classes Defined:* ContentPart(0 methods)
  - *Global Functions:* render_with_latex, split_for_hybrid_render, extract_equations, has_equations
- **`markdown_exporter.py`**
  - *Purpose:* Markdown Exporter for RAG Responses.
  - *Classes Defined:* None
  - *Global Functions:* format_answer_as_markdown, format_conversation_as_markdown, escape_markdown
- **`monitoring.py`**
  - *Purpose:* SME Research Assistant - Monitoring Module
  - *Classes Defined:* RunContext(6 methods), StepTracker(7 methods)
  - *Global Functions:* start_run, end_run
- **`question_classifier.py`**
  - *Purpose:* Question Classifier for Dynamic Paper Selection.
  - *Classes Defined:* QuestionClassification(0 methods)
  - *Global Functions:* classify_question, get_paper_range, get_classification_info
- **`reference_splitter.py`**
  - *Purpose:* Reference Splitter for SME RAG System (Phase 21).
  - *Classes Defined:* None
  - *Global Functions:* extract_author_surname, split_references, split_references_by_doi, format_split_references
- **`session_cache.py`**
  - *Purpose:* Session Cache for Sequential RAG.
  - *Classes Defined:* CacheEntry(0 methods), SessionCache(10 methods)
  - *Global Functions:* create_session_cache
- **`text_cleaner.py`**
  - *Purpose:* Text Cleaner for PDF Extraction Artifacts.
  - *Classes Defined:* TextCleaner(2 methods)
  - *Global Functions:* clean_text, clean_chunk_text, batch_clean
- **`time_estimator.py`**
  - *Purpose:* Time Estimator for RAG Queries.
  - *Classes Defined:* None
  - *Global Functions:* estimate_time, format_time_estimate, get_time_breakdown

#### Directory: `src\_deprecated`
- **`paper_db.py`**
  - *Purpose:* DEPRECATED: This file was archived on 2026-02-02.
  - *Classes Defined:* PaperRecord(2 methods), PaperDatabase(14 methods)
  - *Global Functions:* migrate_json_to_sqlite

## 2. Database Schemas (SQLite/Postgres equivalent)
**Table:** `dead_letter_queue` (from `src\pipeline/dead_letter_queue.py`)
```sql
CREATE TABLE dead_letter_queue (id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending')
```
**Table:** `audit_log` (from `src\security/audit.py`)
```sql
CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    user_id TEXT,
                    session_id TEXT,
                    action TEXT NOT NULL,
                    details TEXT,
                    ip_address TEXT,
                    duration_ms REAL,
                    created_at REAL NOT NULL)
```
**Table:** `papers` (from `src\storage/schema.py`)
```sql
CREATE TABLE papers (id INTEGER PRIMARY KEY AUTOINCREMENT,
    unique_id TEXT UNIQUE NOT NULL,    -- canonical ID (doi:..., arxiv:..., or title:...)
```
**Table:** `pipeline_state` (from `src\storage/schema.py`)
```sql
CREATE TABLE pipeline_state (key TEXT PRIMARY KEY,
    value TEXT,                        -- JSON value
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```
**Table:** `chunks` (from `src\storage/schema.py`)
```sql
CREATE TABLE chunks (id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER,
    chunk_index INTEGER,
    text TEXT,
    metadata TEXT,                     -- JSON metadata
    FOREIGN KEY(paper_id)
```
**Table:** `dead_letter_queue` (from `src\storage/schema.py`)
```sql
CREATE TABLE dead_letter_queue (id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL,
    stage TEXT NOT NULL,        -- 'chunk', 'embed', 'store'
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending'  -- 'pending', 'retried', 'abandoned')
```
**Table:** `papers` (from `src\_deprecated/paper_db.py`)
```sql
CREATE TABLE papers (id INTEGER PRIMARY KEY AUTOINCREMENT,
        doi TEXT UNIQUE NOT NULL,
        title TEXT,
        authors TEXT,
        year INTEGER,
        venue TEXT,
        abstract TEXT,
        pdf_url TEXT,
        pdf_path TEXT,
        chunk_file TEXT,
        status TEXT DEFAULT 'discovered',
        source TEXT DEFAULT 'unknown',
        discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT,
        metadata TEXT)
```

## 3. LLM Interaction Prompts & Templates
- **File:** `src\academic_v2/drafter.py`
  - **Variable:** `prompt`
  - **Preview:** `YOU ARE AN ACADEMIC WRITER. YOUR TASK IS TO PRODUCE ONE HIGH-QUALITY, ANALYTICALLY RIGOROUS PARAGRAPH THAT INTEGRATES ALL PROVIDED EVIDENCE.  CRITICAL CONSTRAINTS (YOU MUST FOLLOW EACH ONE EXACTLY): 1... [TRUNCATED]`
- **File:** `src\academic_v2/drafter.py`
  - **Variable:** `prompt`
  - **Preview:** `WRITE PARAGRAPH {order} FOR SECTION '{sec_name}'.  THESIS: {thesis} TRANSITION IN: {trans_in or "None"}  ASSIGNED EVIDENCE: {evidence_str} INSTRUCTIONS: - BEGIN WITH THE GIVEN TRANSITION/THESIS. - INT... [TRUNCATED]`
- **File:** `src\academic_v2/librarian.py`
  - **Variable:** `prompt`
  - **Preview:** `Analyze the text below. **EXTRACT EVERY DISCRETE SCIENTIFIC CLAIM** and return them as a JSON list exactly matching the schema described in the system prompt.  TEXT TO ANALYZE: {context_text}  RETURN ... [TRUNCATED]`
- **File:** `src\generation/prompts.py`
  - **Variable:** `PROMPT`
  - **Preview:** `You are an expert research assistant helping users understand academic literature.  Your knowledge comes ONLY from the provided context excerpts from academic papers.  CRITICAL RULES: 1. EVERY factual... [TRUNCATED]`
- **File:** `src\retrieval/clarification_analyzer.py`
  - **Variable:** `PROMPT`
  - **Preview:** `Analyze this research question and determine if clarification is needed before searching.  QUESTION: {query}  Determine if clarification would significantly improve the search. Only ask clarifying que... [TRUNCATED]`
- **File:** `src\retrieval/gap_analyzer.py`
  - **Variable:** `PROMPT`
  - **Preview:** `Analyze the search results for gaps in evidence needed to answer this question.  QUESTION: {query}  AVAILABLE CONTEXT (summary): {context_summary}  Respond with ONLY valid JSON in this exact format: {... [TRUNCATED]`
- **File:** `src\retrieval/hyde.py`
  - **Variable:** `prompt`
  - **Preview:** `You are a research paper writing assistant. Given a research question,  write a short paragraph (3-5 sentences) that would appear in a scientific paper answering this question. Write in academic style... [TRUNCATED]`
- **File:** `src\retrieval/query_expander.py`
  - **Variable:** `prompt`
  - **Preview:** `Analyze this research question and break it into independent sub-questions  that can be searched separately.   CONSTRAINTS: - You MUST return between {min_q} and {max_q} sub-questions. - Return only t... [TRUNCATED]`
- **File:** `src\retrieval\sequential/generation.py`
  - **Variable:** `prompt`
  - **Preview:** `Write the "{section_title}" section for a research response.  ORIGINAL QUESTION: {query}  CONTEXT (from {available_sources} research papers): {section_context} {redundancy_instruction}  {valid_citatio... [TRUNCATED]`
- **File:** `src\retrieval\sequential/generation.py`
  - **Variable:** `prompt`
  - **Preview:** `You are an academic writer producing thesis-quality research content.  Cite sources meticulously inline.   ETHICAL RULE: You are in strict CLOSED-BOOK mode. You may ONLY cite authors found in the 'VAL... [TRUNCATED]`
- **File:** `src\retrieval\sequential/generation.py`
  - **Variable:** `prompt`
  - **Preview:** `The following academic text was cut off mid-sentence or mid-citation.  Complete it naturally with 1-2 more sentences. Ensure all parentheses and citations are properly closed.  TEXT TO COMPLETE: {cont... [TRUNCATED]`
- **File:** `src\retrieval\sequential/generation.py`
  - **Variable:** `prompt`
  - **Preview:** `Write the "{final_title}" section for this research response.  PROOFREAD CONTENT (all previous sections - this is the finalized content): {proofread_content}  ORIGINAL QUESTION: {query}  AVAILABLE SOU... [TRUNCATED]`
- **File:** `src\retrieval\sequential/generation.py`
  - **Variable:** `prompt`
  - **Preview:** `You are an academic writer producing a synthesis conclusion. Be insightful, not repetitive. Focus on implications and recommendations. Match the writing style of the provided content. Use American Eng... [TRUNCATED]`
- **File:** `src\retrieval\sequential/planning.py`
  - **Variable:** `prompt`
  - **Preview:** `Analyze the search results below for the query: "{query}"  SEARCH FINDINGS: {snippets_text}  TASK: Create a 'Knowledge Map' summary of the available literature. 1. Identify 3-5 distinct thematic clust... [TRUNCATED]`
- **File:** `src\retrieval\sequential/planning.py`
  - **Variable:** `prompt`
  - **Preview:** `You are a research orchestrator planning an academic response structure.  QUERY: "{query}" DEPTH: {depth} TARGET PAPERS: {target_papers}  TASK: Plan the section structure and unique citation allocatio... [TRUNCATED]`
- **File:** `src\retrieval\sequential/planning.py`
  - **Variable:** `prompt`
  - **Preview:** `You are a deterministic research planner. Your role is to create structured, consistent research outlines.  CRITICAL RULES: 1. Return ONLY valid JSON - no markdown, no explanations 2. Follow unique ci... [TRUNCATED]`
- **File:** `src\retrieval\sequential/planning.py`
  - **Variable:** `prompt`
  - **Preview:** `You are creating an outline for a research response.  Question: "{query}"  Generate EXACTLY {section_count} section titles for a comprehensive answer. Include these types of sections as appropriate: -... [TRUNCATED]`
- **File:** `src\retrieval\sequential/proofreading.py`
  - **Variable:** `prompt`
  - **Preview:** `You are a COPY-EDITOR making MINIMAL corrections.  SECTION: {section}  CORRECTIONS (ALL REQUIRED): 1. Fix grammar and syntax errors 2. Fix duplicate/repeated phrases 3. Remove redundant sentences (exa... [TRUNCATED]`
- **File:** `src\retrieval\sequential/proofreading.py`
  - **Variable:** `prompt`
  - **Preview:** `Extract metadata from this section.  SECTION: {section[:2000]}  # First 2000 chars for efficiency  OUTPUT (JSON): {{   "section_num": {section_num},   "title": "{title}",   "purpose": "2-3 sentence su... [TRUNCATED]`
- **File:** `src\retrieval\sequential/proofreading.py`
  - **Variable:** `prompt`
  - **Preview:** `Extract metadata for each section below.  {sections_text}  OUTPUT (JSON array with one object per section): [   {{"section_num": 1, "title": "...", "purpose": "1-2 sentences", "key_claims": ["claim1",... [TRUNCATED]`
- **File:** `src\retrieval\sequential/proofreading.py`
  - **Variable:** `prompt`
  - **Preview:** `Review these section fingerprints for structural issues.  FINGERPRINTS: {fingerprints_text}  IDENTIFY: 1. Redundancy (same claims in multiple sections) 2. Terminology inconsistencies 3. Missing transi... [TRUNCATED]`
- **File:** `src\retrieval\sequential/proofreading.py`
  - **Variable:** `prompt`
  - **Preview:** `Apply this SPECIFIC edit to the section.  SECTION: {section}  EDIT INSTRUCTION: {action}  ADDITIONAL (only if needed after applying the edit): - If sentences transition abruptly after your edit, add a... [TRUNCATED]`
- **File:** `src\retrieval\sequential/reflection.py`
  - **Variable:** `prompt`
  - **Preview:** `You are a senior research methodology expert.  Review the user's question and the initial search results.  User Question: {original_query}  Available Context Summary (first 3000 chars): {context[:3000... [TRUNCATED]`
- **File:** `src\retrieval\sequential/search.py`
  - **Variable:** `prompt`
  - **Preview:** `Review these search results for the user's query.          QUERY: "{query}"  RESULTS (Top 10): {audit_view}  TASK: Does this result set cover ALL distinct aspects of the query? 1. Identify Key Informa... [TRUNCATED]`
- **File:** `src\retrieval\sequential/search.py`
  - **Variable:** `prompt`
  - **Preview:** `You are a research search query generator performing HIERARCHICAL follow-up.  The user asked: "{original_query}" {results_context}  Generate 2-3 SPECIFIC follow-up search queries that would find: 1. D... [TRUNCATED]`
## 4. Qdrant Vector DB Assumed Payload Metadata
Based on the semantic streaming ingestion pipeline, Qdrant heavily leverages the following metadata dictionary structures per tensor chunk:
```json
{
  "doi": "10.xxxx/yyyy",
  "chunk_id": "c_12345",
  "text": "The raw chunk text extracted via PyMuPDF limit.",
  "apa_reference": "Hardbound string generated by PaperDiscoverer natively.",
  "page": 5,
  "depth_tier": "High"
}
```