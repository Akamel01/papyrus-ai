# Query Processing Workflow: High Depth + Section Mode

**Version:** 1.0
**Last Updated:** March 2026
**Audience:** Developers, Performance Engineers, System Administrators

---

## Overview

This document provides a complete technical specification of the query processing workflow when using **Investigation Depth: High** with **Section Mode: On** in the SME Research Assistant Chat UI. The goal is to enable optimization for better accuracy, reduced latency, and more efficient token usage.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [High-Level Flowchart](#high-level-flowchart)
3. [Depth Preset Configuration](#depth-preset-configuration)
4. [Phase-by-Phase Breakdown](#phase-by-phase-breakdown)
5. [LLM Call Inventory](#llm-call-inventory)
6. [Search Operations Inventory](#search-operations-inventory)
7. [Token Usage Analysis](#token-usage-analysis)
8. [Latency Breakdown](#latency-breakdown)
9. [Optimization Opportunities](#optimization-opportunities)
10. [Configuration Reference](#configuration-reference)
11. [Monitoring and Diagnostics](#monitoring-and-diagnostics)

---

## Executive Summary

| Metric | High Depth + Section Mode |
|--------|---------------------------|
| **LLM Calls** | 18-26 per query |
| **Search Operations** | 10-20 per query |
| **Token Usage** | ~175,000-200,000 tokens |
| **Typical Latency** | 3-8 minutes |
| **Primary Bottleneck** | Cross-encoder reranking (45% of latency) |

### Key Characteristics

- **Multi-round search**: Initial broad scan + hierarchical follow-up
- **Section-by-section generation**: Each section gets dedicated search
- **Multi-pass proofreading**: 3-pass editing system
- **Evidence-first architecture**: Claims extracted before synthesis

---

## High-Level Flowchart

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         USER QUERY INPUT                                     │
│                    "Investigation Depth: High"                               │
│                    "Section Mode: On"                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 1: INITIAL RESEARCH SCAN                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ Load Preset  │→ │ Query        │→ │ HyDE         │→ │ Hybrid       │    │
│  │ (High)       │  │ Expansion    │  │ Generation   │  │ Search       │    │
│  │              │  │ (2-4 subs)   │  │              │  │ (BM25+Sem)   │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
│                                                               │              │
│                           ┌───────────────────────────────────┘              │
│                           ▼                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                       │
│  │ Reactive     │→ │ Reranking    │→ │ Context      │                       │
│  │ Audit        │  │ (Cross-Enc)  │  │ Building     │                       │
│  └──────────────┘  └──────────────┘  └──────────────┘                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 2: HIERARCHICAL FOLLOW-UP (High Depth Only)                          │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ Force hierarchical drilling → Generate targeted micro-queries        │   │
│  │ → Search Round 2 → Merge results                                     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 3: KNOWLEDGE LANDSCAPE                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ Analyze top 150 results → Identify thematic clusters                 │   │
│  │ → Map evidence volume (High/Med/Low) → Identify gaps                 │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 4: SECTION ORCHESTRATION                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ LLM Orchestration: Plan 5-8 sections with citation allocation        │   │
│  │ → Validate structure → Fallback to algorithmic if needed             │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 5: PER-SECTION GENERATION (Loop × 5-8 sections)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ Section      │→ │ Inject P1    │→ │ Reranking    │→ │ Evidence-    │    │
│  │ Search       │  │ Results      │  │              │  │ First Gen    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
│                                                               │              │
│                                                               ▼              │
│                                              ┌──────────────────────────┐   │
│                                              │ Stream Section to UI     │   │
│                                              └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 6: REFERENCE AGGREGATION                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ Deduplicate DOIs → Split by citation status → Format APA             │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 7: MULTI-PASS PROOFREADING                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ Pass 1:      │→ │ Batch        │→ │ Pass 2:      │→ │ Pass 3a:     │    │
│  │ Copy-Edit    │  │ Fingerprint  │  │ Structural   │  │ Targeted     │    │
│  │ (per sect)   │  │ Extraction   │  │ Review       │  │ Edits        │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 8: FINAL SECTION & ASSEMBLY                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ Generate Conclusion → Append References → Compliance Check           │   │
│  │ → Return Complete Response                                           │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Depth Preset Configuration

High depth preset values from `src/config/depth_presets.py`:

```python
"High": {
    "description": "Deep dive - 50 papers, thorough synthesis",
    "min_unique_papers": 50,
    "max_per_doi": 5,
    "sub_query_limit": (2, 4),      # 2-4 sub-queries for expansion
    "top_k_initial": 120,           # Candidates per search
    "top_k_rerank": 100,            # After reranking
    "top_k_final": 80,              # Final context selection
    "max_tokens": 42000,            # Output token limit
    "use_hyde": True,               # HyDE enabled
    "use_query_expansion": True,    # Query expansion enabled
    "temperature": 0.2,
    "search_params": {
        "ef_search": 1200,          # HNSW search parameter
        "oversampling": 4.0,        # Quantization correction
        "use_quantization": True
    }
}
```

### Comparison with Other Depths

| Parameter | Low | Medium | High |
|-----------|-----|--------|------|
| min_unique_papers | 10 | 25 | **50** |
| sub_query_limit | (1,2) | (1,3) | **(2,4)** |
| top_k_initial | 25 | 50 | **120** |
| top_k_rerank | 20 | 40 | **100** |
| use_hyde | False | True | **True** |
| use_query_expansion | False | True | **True** |
| ef_search | 128 | 200 | **1200** |

---

## Phase-by-Phase Breakdown

### Phase 1: Initial Research Scan

**Location:** `src/retrieval/sequential/search.py` - `_do_search()`

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PHASE 1: INITIAL RESEARCH SCAN                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Step 1.1: Load Preset                                               │
│  ├── Load "High" preset from depth_presets.py                       │
│  └── Extract: top_k_initial=120, sub_query_limit=(2,4), etc.        │
│                                                                      │
│  Step 1.2: Query Expansion                                           │
│  ├── LLM Call: Decompose query into 2-4 sub-queries                 │
│  ├── Input: Original user query                                     │
│  ├── Output: List of focused sub-queries                            │
│  └── Tokens: ~1,500 (input) + ~200 (output)                         │
│                                                                      │
│  Step 1.3: HyDE Generation                                           │
│  ├── LLM Call: Generate hypothetical document                       │
│  ├── Input: Query + prompt (~500 tokens)                            │
│  ├── Output: 3-5 sentence academic paragraph (~300 tokens)          │
│  ├── Embed: 4096-dim vector via Qwen3-Embedding                     │
│  └── Tokens: ~800 total                                              │
│                                                                      │
│  Step 1.4: Hybrid Search (per sub-query)                             │
│  ├── Semantic: Query Qdrant with HyDE embedding                     │
│  │   ├── Parameters: ef_search=1200, top_k=120                      │
│  │   └── Returns: 120 chunks with cosine similarity scores          │
│  ├── BM25: Query Tantivy index                                      │
│  │   ├── Tokenization: Word-level                                   │
│  │   └── Returns: 120 chunks with BM25 scores                       │
│  └── RRF Fusion: Combine scores                                     │
│      ├── Formula: score = 0.7 * (1/(k+sem_rank)) +                  │
│      │                    0.3 * (1/(k+bm25_rank))                   │
│      └── k = 60 (RRF constant from thresholds.py)                   │
│                                                                      │
│  Step 1.5: Deduplication                                             │
│  ├── Remove duplicate chunk_ids                                      │
│  └── Typical reduction: 480 → 250 unique chunks                     │
│                                                                      │
│  Step 1.6: Reactive Audit (High/Medium only)                         │
│  ├── LLM Call: Analyze top 10 results for coverage                  │
│  ├── Decision: SUFFICIENT | MISSING | RESTRUCTURE                   │
│  ├── If MISSING: Additional targeted search                         │
│  └── Tokens: ~2,000                                                  │
│                                                                      │
│  Step 1.7: Reranking (Cross-Encoder)                                 │
│  ├── Model: BAAI/bge-reranker-v2-m3 or OllamaReranker               │
│  ├── Input: All candidate chunks (250+)                             │
│  ├── Batch processing: 128 pairs per batch                          │
│  ├── Output: top_k_rerank=100 highest scoring                       │
│  └── Latency: 15-45 seconds (GPU dependent)                         │
│                                                                      │
│  Step 1.8: Context Building                                          │
│  ├── Select top 80 chunks (top_k_final)                             │
│  ├── Enforce max_per_doi=5 (diversity)                              │
│  ├── Target: 50 unique papers minimum                               │
│  └── Build APA references and DOI map                               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 2: Hierarchical Follow-Up

**Location:** `src/retrieval/sequential_rag.py` - `process_with_reflection()`

For **High depth specifically**, a follow-up round is always forced regardless of initial paper count:

```
┌─────────────────────────────────────────────────────────────────────┐
│                PHASE 2: HIERARCHICAL FOLLOW-UP                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Trigger Condition (High Depth):                                     │
│  ├── Always forced for depth == "High"                              │
│  └── OR if unique_papers < 12 (threshold)                           │
│                                                                      │
│  Step 2.1: Generate Follow-Up Queries                                │
│  ├── LLM Call: Analyze initial results + generate micro-queries    │
│  ├── Context: Top 30 paper titles from Round 1                      │
│  ├── Output: 2-3 targeted queries for gaps                          │
│  └── Focus: Methodological gaps, quantitative data, edge cases      │
│                                                                      │
│  Step 2.2: Round 2 Search (1/4 presets)                              │
│  ├── top_k_override: 30 (vs 120 in Round 1)                         │
│  ├── Purpose: Focused micro-search, not broad                       │
│  └── Merge results with Round 1 pool                                │
│                                                                      │
│  Step 2.3: Re-rank Combined Pool                                     │
│  └── Apply same reranking to merged results                         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 3: Knowledge Landscape

**Location:** `src/retrieval/sequential/planning.py` - `_generate_topic_landscape()`

```
┌─────────────────────────────────────────────────────────────────────┐
│                   PHASE 3: KNOWLEDGE LANDSCAPE                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Step 3.1: Prepare Snippets                                          │
│  ├── Input: Top 150 reranked results (High depth)                   │
│  ├── Extract: Title, year, first 300 chars                          │
│  └── Format for LLM analysis                                        │
│                                                                      │
│  Step 3.2: Generate Knowledge Map                                    │
│  ├── LLM Call: Identify thematic clusters                           │
│  ├── Output Structure:                                               │
│  │   ├── Cluster: [Name] (Evidence: High/Med/Low)                   │
│  │   ├── Cluster: [Name] (Evidence: High/Med/Low)                   │
│  │   └── Missing/Gaps: [Topic A], [Topic B]                         │
│  └── Tokens: ~15,000 (input) + ~2,000 (output)                      │
│                                                                      │
│  Purpose:                                                            │
│  ├── Inform section planning with actual evidence                   │
│  ├── Prevent "filter bubble" (standard topics not in search)        │
│  └── Guide citation allocation per section                          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 4: Section Orchestration

**Location:** `src/retrieval/sequential/planning.py` - `_orchestrate_sections()`

```
┌─────────────────────────────────────────────────────────────────────┐
│                   PHASE 4: SECTION ORCHESTRATION                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Step 4.1: LLM Orchestration                                         │
│  ├── Input:                                                          │
│  │   ├── Query, Depth=High, Target Papers=50                        │
│  │   └── Knowledge Map from Phase 3                                  │
│  ├── LLM Call: Plan unified section structure                       │
│  ├── Output JSON:                                                    │
│  │   {                                                               │
│  │     "sections": [                                                 │
│  │       {"title": "...", "citations": N, "focus": "..."},          │
│  │       ...                                                         │
│  │     ]                                                             │
│  │   }                                                               │
│  └── Tokens: ~3,000 (input) + ~1,000 (output)                       │
│                                                                      │
│  Step 4.2: Validation                                                │
│  ├── Check section count: 5-8 for High depth                        │
│  ├── Ensure minimum 3 citations per section                         │
│  ├── Verify total citations >= 50                                   │
│  └── Scale up proportionally if under target                        │
│                                                                      │
│  Step 4.3: Fallback (if LLM fails)                                   │
│  ├── Use algorithmic section count determination                    │
│  ├── Generate outline via separate LLM call                         │
│  └── Distribute citations evenly                                    │
│                                                                      │
│  High Depth Section Limits:                                          │
│  ├── Ideal: 5-8 sections                                            │
│  ├── Soft limit: 10 sections (warn but accept)                      │
│  └── Hard limit: >10 → condense via merging                         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 5: Per-Section Generation

**Location:** `src/retrieval/sequential_rag.py` - `_process_with_sections_core()`

This phase loops for each planned section (5-8 for High depth):

```
┌─────────────────────────────────────────────────────────────────────┐
│         PHASE 5: PER-SECTION GENERATION (× 5-8 sections)             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  For each section in orchestration plan:                             │
│                                                                      │
│  Step 5.1: Section-Specific Search                                   │
│  ├── Query: section["focus"] (e.g., "crash modification factors")   │
│  ├── Inject: Phase 1 reranked results (ensures global context)      │
│  ├── Context Builder: Dynamic limits from AdaptiveTokenManager      │
│  │   └── max_context_tokens varies by section importance            │
│  └── Diversity: max_per_doi=3 (prevent single-paper domination)     │
│                                                                      │
│  Step 5.2: Reranking                                                 │
│  └── Cross-encoder rerank section-specific results                  │
│                                                                      │
│  Step 5.3: Evidence-First Generation (V2)                            │
│  ├── Location: src/academic_v2/engine.py                            │
│  ├── Extract claims from search results                             │
│  ├── Build claim graph with citations                               │
│  ├── Generate section text grounded in claims                       │
│  └── Output: SectionResult with content + cited DOIs                │
│                                                                      │
│  Step 5.4: Stream to UI                                              │
│  ├── Yield GenerationProgress(type="section")                       │
│  └── User sees section immediately                                  │
│                                                                      │
│  Step 5.5: Track Coverage                                            │
│  ├── Extract key points for redundancy tracking                     │
│  └── Pass to subsequent sections                                    │
│                                                                      │
│  Tokens per section: ~8,000-15,000 (context + generation)            │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 6: Reference Aggregation

**Location:** `src/retrieval/sequential_rag.py` - `_aggregate_references()`

```
┌─────────────────────────────────────────────────────────────────────┐
│                  PHASE 6: REFERENCE AGGREGATION                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Step 6.1: Collect All DOIs                                          │
│  ├── Merge DOIs from all section results                            │
│  └── Merge DOIs from all reranked pools                             │
│                                                                      │
│  Step 6.2: DOI-Based Splitting                                       │
│  ├── cited_refs: Papers actually cited in text                      │
│  └── uncited_refs: Retrieved but not cited                          │
│                                                                      │
│  Step 6.3: Format APA References                                     │
│  ├── Sort alphabetically by first author                            │
│  ├── Format: Author, A. B. (Year). Title. Journal. DOI              │
│  └── Separate sections: "References" + "Additional Sources"         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 7: Multi-Pass Proofreading

**Location:** `src/retrieval/sequential/proofreading.py` - `_multipass_proofread()`

```
┌─────────────────────────────────────────────────────────────────────┐
│                  PHASE 7: MULTI-PASS PROOFREADING                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Pass 1: Micro-Level Copy-Editing (per section)                      │
│  ├── LLM Call × N sections                                          │
│  ├── Fix: Grammar, syntax, duplicate phrases                        │
│  ├── Fix: Unclosed citation parentheses                             │
│  ├── Preserve: All content, numbers, statistics, citations          │
│  ├── Length validation: Output must be ±10% of input                │
│  ├── Retry logic: Up to 3 attempts if too short                     │
│  └── Tokens: ~10,000 per section                                    │
│                                                                      │
│  Batch Fingerprinting (LATENCY OPTIMIZATION)                         │
│  ├── Single LLM Call (vs N separate calls)                          │
│  ├── Extract: Purpose, key claims, key terms per section            │
│  └── Output: JSON array of fingerprints                             │
│                                                                      │
│  Pass 2: Macro-Level Structural Review                               │
│  ├── Single LLM Call                                                │
│  ├── Input: All section fingerprints                                │
│  ├── Identify: Redundancy, terminology inconsistencies              │
│  ├── Output: JSON with edit_instructions array                      │
│  └── Filter: Reject vague instructions ("improve clarity")          │
│                                                                      │
│  Pass 3a: Targeted Structural Edits                                  │
│  ├── LLM Call × M (number of edit instructions)                     │
│  ├── Apply SPECIFIC edits from Pass 2                               │
│  ├── Add transitions only if flow disrupted                         │
│  ├── Length validation: Reject if >10% shorter                      │
│  └── Fallback: Keep original if edit too aggressive                 │
│                                                                      │
│  Total Proofreading Tokens: ~60,000-80,000                           │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 8: Final Assembly

**Location:** `src/retrieval/sequential_rag.py` - end of `_process_with_sections_core()`

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PHASE 8: FINAL ASSEMBLY                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Step 8.1: Deferred Final Section                                    │
│  ├── Generate Conclusion/Summary AFTER proofreading                 │
│  ├── Input: Proofread content + source list                         │
│  ├── LLM Call: Synthesize key findings                              │
│  └── Append to response                                             │
│                                                                      │
│  Step 8.2: Append References                                         │
│  ├── Format: "## References" + cited refs                           │
│  └── Format: "## Additional Sources" + uncited refs                 │
│                                                                      │
│  Step 8.3: Compliance Check                                          │
│  ├── Validate citation count and format                             │
│  ├── Generate compliance badge (Good/Fair/Poor)                     │
│  └── Determine confidence level based on unique sources             │
│                                                                      │
│  Step 8.4: Return Complete Response                                  │
│  ├── response: Full text with all sections                          │
│  ├── sources: List of source metadata                               │
│  ├── confidence: "High"/"Medium"/"Low"                              │
│  ├── apa_references: List of formatted references                   │
│  ├── compliance_badge: "Good"/"Fair"/"Poor"                         │
│  └── proofreading_notes: List of any warnings                       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## LLM Call Inventory

### Complete Call List (High Depth, Section Mode)

| # | Phase | Call Purpose | Tokens (Approx) | Required? |
|---|-------|--------------|-----------------|-----------|
| 1 | 1.2 | Query Expansion | 1,700 | Yes |
| 2 | 1.3 | HyDE Generation | 800 | Yes |
| 3 | 1.6 | Reactive Audit | 2,000 | High/Med |
| 4 | 2.1 | Follow-Up Query Gen | 600 | High only |
| 5 | 2.2 | Round 2 HyDE | 800 | If follow-up |
| 6 | 3.2 | Knowledge Map | 17,000 | Yes |
| 7 | 4.1 | Section Orchestration | 4,000 | Yes |
| 8-13 | 5.3 | Section Generation ×6 | 60,000 | Yes |
| 14 | 7.1a | Fingerprint Batch | 3,000 | Yes |
| 15-20 | 7.1 | Pass 1 Proofread ×6 | 60,000 | Yes |
| 21 | 7.2 | Pass 2 Structural | 4,000 | Yes |
| 22-24 | 7.3 | Pass 3a Edits ×3 | 15,000 | If needed |
| 25 | 8.1 | Final Section | 5,000 | Yes |

**Total: 18-26 LLM calls, ~175,000 tokens**

### Call Reduction Opportunities

| Optimization | Calls Saved | Tokens Saved |
|--------------|-------------|--------------|
| Skip HyDE for simple queries | 1-2 | 1,600 |
| Batch fingerprints (already done) | N-1 | 3,000 |
| Skip Pass 3a if no edits | 0-5 | 15,000 |
| Combine Pass 1 for short sections | 0-3 | 10,000 |

---

## Search Operations Inventory

| # | Phase | Operation | Index | Results |
|---|-------|-----------|-------|---------|
| 1 | 1.4 | HyDE Vector Search | Qdrant | 120 |
| 2 | 1.4 | Primary Hybrid (BM25) | Tantivy | 120 |
| 3 | 1.4 | Primary Hybrid (Semantic) | Qdrant | 120 |
| 4-6 | 1.4 | Sub-query Hybrid ×3 | Both | 360 |
| 7 | 1.6 | Reactive Audit Search | Both | 120 |
| 8-9 | 2.2 | Round 2 Search ×2 | Both | 60 |
| 10-15 | 5.1 | Section Search ×6 | Both | 720 |

**Total: 10-20 search operations**

---

## Token Usage Analysis

### Breakdown by Phase

| Phase | Input Tokens | Output Tokens | Total |
|-------|--------------|---------------|-------|
| 1. Initial Scan | 5,000 | 1,500 | 6,500 |
| 2. Follow-Up | 2,000 | 800 | 2,800 |
| 3. Knowledge Map | 15,000 | 2,000 | 17,000 |
| 4. Orchestration | 3,000 | 1,000 | 4,000 |
| 5. Section Gen ×6 | 48,000 | 24,000 | 72,000 |
| 7. Proofreading | 50,000 | 30,000 | 80,000 |
| 8. Final Assembly | 3,000 | 2,000 | 5,000 |
| **TOTAL** | **126,000** | **61,300** | **~187,300** |

### Token Optimization Targets

1. **Proofreading (43%)**: Most expensive phase
   - Consider: Skip for simple queries
   - Consider: Single-pass for Low depth

2. **Section Generation (38%)**: Core functionality
   - Consider: Reduce context size per section
   - Consider: Shorter sections for Medium depth

3. **Knowledge Map (9%)**: Planning overhead
   - Consider: Skip for narrow queries
   - Consider: Reuse across similar queries

---

## Latency Breakdown

### Typical Timing (High Depth)

| Phase | Duration | % Total | Primary Bottleneck |
|-------|----------|---------|-------------------|
| Initial Search | 5-10s | 3% | Network latency |
| Reranking (R1) | 20-45s | 20% | GPU inference |
| Follow-Up Search | 3-5s | 2% | Network |
| Reranking (R2) | 10-20s | 8% | GPU inference |
| Knowledge Map | 10-15s | 7% | LLM generation |
| Orchestration | 5-8s | 3% | LLM generation |
| Section Gen ×6 | 60-120s | 45% | LLM generation |
| Proofreading | 30-60s | 20% | LLM generation |
| Assembly | 2-5s | 2% | Compute |
| **TOTAL** | **145-288s** | **100%** | |

### Latency Optimization Targets

1. **Reranking (28%)**: GPU-bound
   - Cache reranker model in GPU memory (already done)
   - Reduce candidate count for follow-up
   - Consider: Hybrid CPU/GPU batching

2. **Section Generation (45%)**: LLM-bound
   - Stream responses (already done)
   - Parallelize independent sections (not currently done)
   - Consider: Smaller model for initial drafts

3. **Proofreading (20%)**: LLM-bound
   - Batch fingerprinting (already optimized)
   - Skip passes for short responses
   - Consider: Rule-based pre-filter

---

## Optimization Opportunities

### High Priority (Significant Impact)

| ID | Optimization | Latency Saved | Tokens Saved | Complexity |
|----|--------------|---------------|--------------|------------|
| O1 | Parallel section generation | 30-50% | 0 | High |
| O2 | Adaptive proofreading (skip for simple) | 15-20% | 40,000 | Medium |
| O3 | Reranker result caching | 10-15% | 0 | Medium |
| O4 | Early termination for sufficient results | 5-10% | 10,000 | Low |

### Medium Priority (Moderate Impact)

| ID | Optimization | Latency Saved | Tokens Saved | Complexity |
|----|--------------|---------------|--------------|------------|
| O5 | Skip HyDE for keyword queries | 3-5% | 1,600 | Low |
| O6 | Reduce context per section | 5-10% | 20,000 | Medium |
| O7 | Knowledge Map caching | 5-7% | 17,000 | Medium |
| O8 | Streaming orchestration | 2-3% | 0 | Low |

### Low Priority (Minor Impact)

| ID | Optimization | Latency Saved | Tokens Saved | Complexity |
|----|--------------|---------------|--------------|------------|
| O9 | Combine small sections in Pass 1 | 2-3% | 5,000 | Low |
| O10 | Pre-filter Pass 2 instructions | 1-2% | 2,000 | Low |
| O11 | Async reference formatting | 1% | 0 | Low |

### Implementation Details

#### O1: Parallel Section Generation

Current: Sequential loop over sections
Proposed: Generate 2-3 sections concurrently using asyncio

```python
# Pseudocode
async def generate_sections_parallel(sections, max_concurrent=3):
    semaphore = asyncio.Semaphore(max_concurrent)
    async def gen_section(section):
        async with semaphore:
            return await self._generate_section_async(section)
    return await asyncio.gather(*[gen_section(s) for s in sections])
```

Considerations:
- GPU memory constraints (may limit concurrency)
- Order preservation for streaming
- Error handling across parallel tasks

#### O2: Adaptive Proofreading

Current: Always 3-pass proofreading
Proposed: Skip based on query complexity + response length

```python
# Pseudocode
def should_proofread(query, response, depth):
    complexity = assess_question_complexity(query)
    if depth == "Low":
        return False  # Skip entirely
    if complexity == "simple" and len(response) < 5000:
        return "single_pass"  # Pass 1 only
    return "full"  # All 3 passes
```

#### O3: Reranker Result Caching

Current: Fresh reranking for each search
Proposed: Cache (query_hash, chunk_id) → score for 15 minutes

```python
# Pseudocode
class CachedReranker:
    cache: Dict[str, float] = {}
    ttl: int = 900  # 15 minutes

    def rerank(self, query, results):
        cache_key = hash(query)
        uncached = [r for r in results if (cache_key, r.chunk_id) not in self.cache]
        if uncached:
            new_scores = self._rerank_uncached(query, uncached)
            self._update_cache(cache_key, uncached, new_scores)
        return self._get_cached_results(cache_key, results)
```

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_URL` | `http://sme_ollama:11434` | LLM service URL |
| `QDRANT_URL` | `http://sme_qdrant:6333` | Vector DB URL |
| `RERANKER_MAX_PARALLEL` | `128` | Concurrent reranking requests |
| `RERANKER_TIMEOUT` | `60` | Per-request timeout (seconds) |

### Tunable Parameters

| Parameter | Location | Impact |
|-----------|----------|--------|
| `top_k_initial` | `depth_presets.py` | Search breadth (latency ↔ recall) |
| `top_k_rerank` | `depth_presets.py` | Reranking scope (latency ↔ quality) |
| `ef_search` | `depth_presets.py` | HNSW accuracy (latency ↔ recall) |
| `max_per_doi` | `depth_presets.py` | Citation diversity |
| `sub_query_limit` | `depth_presets.py` | Query expansion scope |

### Model Configuration

| Component | Model | Purpose |
|-----------|-------|---------|
| LLM | gpt-oss:120b-cloud | Response generation |
| Embedder | qwen3-embedding:8b | 4096-dim vectors |
| Reranker | BAAI/bge-reranker-v2-m3 | Cross-encoder scoring |
| Reranker (Ollama) | dengcao/Qwen3-Reranker-0.6B:Q8_0 | Alternative reranker |

---

## Monitoring and Diagnostics

### Key Metrics to Track

| Metric | Location | Warning Threshold |
|--------|----------|-------------------|
| LLM latency per call | StepTracker | > 30s |
| Reranking latency | `_do_search()` | > 60s |
| Unique papers found | Phase 1 output | < 20 for High |
| Section generation time | Per-section | > 30s |
| Proofreading pass time | Per-pass | > 20s |
| Total query time | End-to-end | > 5 min |

### Diagnostic Gates

The system uses `DiagnosticGate` for error handling with configurable severity:

- `critical`: Stops execution, reports error
- `error`: Reports error, continues if suppressible
- `warning`: Logs warning, always continues

Key gates to monitor:
- `Primary Hybrid Search` (critical, suppressed)
- `Knowledge Landscape` (warning, suppressed)
- `Section Writing` (error, suppressed)
- `Proofreading` (error, suppressed)

### Log Messages to Watch

```
# Good: Healthy operation
INFO: Search Intersection: 45 documents found by BOTH methods
INFO: Knowledge Map generated (1234 chars)
INFO: LLM orchestration successful: 6 sections

# Warning: Degraded but functional
WARN: Pass 1 Section 3: Fallback to minimal proofreading
WARN: Orchestration exceeded ideal range (9/8) for High

# Error: Needs investigation
ERROR: Section 4 generation failed (suppressed)
ERROR: Primary search failed (suppressed)
```

---

## Appendix: File Reference

### Core Workflow Files

| File | Purpose |
|------|---------|
| `src/retrieval/sequential_rag.py` | Main orchestrator class |
| `src/retrieval/sequential/search.py` | SearchMixin: search operations |
| `src/retrieval/sequential/planning.py` | PlanningMixin: section planning |
| `src/retrieval/sequential/generation.py` | GenerationMixin: section writing |
| `src/retrieval/sequential/proofreading.py` | ProofreadingMixin: 3-pass editing |

### Supporting Files

| File | Purpose |
|------|---------|
| `src/config/depth_presets.py` | Depth preset configuration |
| `src/retrieval/hybrid_search.py` | BM25 + Semantic fusion |
| `src/retrieval/hyde.py` | Hypothetical document embeddings |
| `src/retrieval/reranker.py` | Cross-encoder reranking |
| `src/retrieval/context_builder.py` | Context assembly |
| `src/utils/adaptive_tokens.py` | Dynamic token allocation |
| `src/academic_v2/engine.py` | Evidence-first generation (V2) |

---

*Document prepared based on source code analysis. Accurate as of March 2026.*
