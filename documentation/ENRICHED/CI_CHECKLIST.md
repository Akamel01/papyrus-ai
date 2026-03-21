# Continuous Integration (CI) Compliance Checklist

As part of the deployment milestone, the deployment pipeline must enforce strict logic bounds verified in the auditing phases. 

The following automated checks must be implemented in the CI/CD pipeline (e.g., GitHub Actions, GitLab CI) to prevent regressions against the `100% auditable` specification target.

## Static Analysis & Linters
- [ ] **Literal Escaping (Bandit or Semgrep)**
  - Enforce zero hardcoded `http://` / `https://` URIs outside of configuration payloads.
  - Fail builds containing hardcoded IPs (excluding `0.0.0.0`, `127.0.0.1` bounded test environments).
  - Explicitly hook `AST` parsing targeting `os.environ.get()` to track runtime parameter decay.
- [ ] **Python Formatting (Black/Ruff)**
  - Enforce deterministic code parsing. Without uniform lines, the `SYSTEM_SYMBOLS_MAP.json` indices will drift against the documentation evidence blocks.
- [ ] **Type Checking (MyPy)**
  - Missing type bounds were identified across several RAG orchestrator mixin boundaries masking function parameter definitions.

## Automated Testing & Integration
- [ ] **Configuration Symmetry Test (`pytest -k "test_config_symmetry"`)**
  - Compare `config.yaml` and `docker_config.yaml` against a runtime execution parsing the `CONFIG_MAP.csv` keys. Check for `KeyError` regressions on start.
- [ ] **RAG Workflow Depth Bounds Simulator**
  - Execute testing mocking `depth_presets.py:L14` assuring `min_unique_papers` ranges dynamically map without statically hardcoded overriding (`sequential_rag.py:L454`).
- [ ] **Container Readiness Probes**
  - Assert the Docker entrypoint commands properly invoke `healthcheck` validations asserting Qdrant cluster locking and Ollama VRAM provisioning.
  - Trigger `docker compose up` in ephemeral CI nodes asserting 0 exit codes upon database migration locking execution (`db_reader.py:L76`).

## Documentation Drift Detection
- [ ] **Spec Sync Action**
  - Invoke `generate_symbols.py` pre-commit hook tracking the total usage bounds against `SYSTEM_SYMBOLS_MAP.json`. If an exported class has zero dependencies matching the specification, the CI pipeline must reject the pull request preventing silent architectural rot.
