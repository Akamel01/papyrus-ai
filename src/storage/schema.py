"""
SME Research Assistant - Database Schema

Defines the SQL schema for the SQLite database.
"""

# Core tables
SCHEMA_SQL = """
-- Papers table: Central registry of all papers
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unique_id TEXT UNIQUE NOT NULL,    -- canonical ID (doi:..., arxiv:..., or title:...)
    doi TEXT,
    arxiv_id TEXT,
    openalex_id TEXT,
    title TEXT,
    authors TEXT,                      -- JSON list of strings
    year INTEGER,
    venue TEXT,
    abstract TEXT,
    pdf_url TEXT,
    status TEXT DEFAULT 'discovered',  -- discovered, downloaded, chunked, embedded, failed
    pdf_path TEXT,                     -- Path relative to project root or absolute
    chunk_file TEXT,                   -- Path to interim chunk file (if any)
    error_message TEXT,
    citation_count INTEGER DEFAULT 0,
    source TEXT,
    metadata TEXT,                     -- JSON dictionary (volume, issue, pages, etc.)
    file_checksum TEXT,                -- SHA256 checksum for duplicate detection
    import_source TEXT,                -- Source of import (e.g., 'manual_import')
    apa_reference TEXT,                -- APA formatted reference
    user_id TEXT,                      -- Multi-user: Owner user ID (NULL = shared/legacy)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
CREATE INDEX IF NOT EXISTS idx_papers_arxiv ON papers(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
CREATE INDEX IF NOT EXISTS idx_papers_year_status ON papers(year, status);
CREATE INDEX IF NOT EXISTS idx_papers_file_checksum ON papers(file_checksum);
CREATE INDEX IF NOT EXISTS idx_papers_user_id ON papers(user_id);
CREATE INDEX IF NOT EXISTS idx_papers_user_status ON papers(user_id, status);

-- Pipeline State table: For resumability and config persistence
CREATE TABLE IF NOT EXISTS pipeline_state (
    key TEXT PRIMARY KEY,
    value TEXT,                        -- JSON value
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Chunks table: Storing chunked text and metadata before embedding
-- Note: Embedded vectors are stored in Qdrant, this is for intermediate text storage
-- and potential future use (e.g. re-embedding without re-parsing)
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER,
    chunk_index INTEGER,
    text TEXT,
    metadata TEXT,                     -- JSON metadata
    FOREIGN KEY(paper_id) REFERENCES papers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_paper_id ON chunks(paper_id);

-- Dead Letter Queue: Captures pipeline items that fail after retry exhaustion
-- Enables post-mortem analysis and manual retry of failed items
CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL,
    stage TEXT NOT NULL,        -- 'chunk', 'embed', 'store'
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending'  -- 'pending', 'retried', 'abandoned'
);
CREATE INDEX IF NOT EXISTS idx_dlq_status ON dead_letter_queue(status);
CREATE INDEX IF NOT EXISTS idx_dlq_paper_id ON dead_letter_queue(paper_id);
"""
