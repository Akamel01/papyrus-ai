# Documentation Index: 100% Auditable Handover Manifest

This directory contains the verified, 100% evidence-backed documentation artifacts tracing the SME pipeline logic directly to the repository state.

## Enriched System Specifications
The following original specifications have been enriched with strict line-level codebase mapping blocks and verification execution scripts.

- [Coverage Based Discovery](COVERAGE_BASED_DISCOVERY_SPEC.enriched.md)
- [Dashboard Architecture](DASHBOARD_ARCHITECTURE_SPEC.enriched.md)
- [Qdrant Hardware Optimizer](QDRANT_OPTIMIZER_SPEC.enriched.md)
- [RAG Workflow Orchestration](RAG_WORKFLOW_SPECIFICATION.enriched.md)
- [Streaming Pipeline](STREAMING_PIPELINE_SPEC.enriched.md)

## Machine-Readable Audit Artifacts
The following JSON, CSV, and Agent-ready Markdown files were programmatically generated scanning `src/`, `app/`, `dashboard/`, and `scripts/`.

- [COMPLETE_REPO_MAP.md](COMPLETE_REPO_MAP.md) - **<font color="red">CRITICAL FOR NEW AI AGENTS</font>** The zero-context blueprint outlining every directory, file, python global, Database SQL Schema, and active LLM Prompt across the entire codebase.
- [SYSTEM_SYMBOLS_MAP.json](SYSTEM_SYMBOLS_MAP.json) - Connects `1251` Python classes, functions, and global constants to their usage dependencies.
- [CONFIG_MAP.csv](CONFIG_MAP.csv) - Tracks `252` OS and YAML configuration requests mapped against active runtime defaults.
- [HARDCODED_LITERALS.csv](HARDCODED_LITERALS.csv) - Logs `90` potential URL, IP, path, and secret literal endpoints embedded in python logic.
- [UNCONFIRMED_ITEMS.json](UNCONFIRMED_ITEMS.json) - Captures three specific claims requiring complex edge-case reproduction commands to strictly verify logic boundaries.

## Verification & Compliance
- [Verification Playbook](HOW_TO_VERIFY.md)
- [CI Checklist](CI_CHECKLIST.md)
- [Final Audit Report](AUDIT_REPORT.md)
