# How To Verify: 100% Auditable Execution Playbook

This playbook provides exact steps, bash commands, and expected outputs to independently verify the technical claims made throughout the Evidence-First `ENRICHED` specification package.

### 1. Verifying Startup Commands and Services
**Goal:** Prove the container environment topology directly matches the orchestration claims in `docker-compose.yml`.

**Command:**
```bash
docker ps --format "{{.Names}}\t{{.Status}}\t{{.Ports}}"
```
**Expected Output:**
```
sme_qdrant         Up 2 days       0.0.0.0:6334-6335->6333-6334/tcp
sme_ollama         Up 2 days       0.0.0.0:11435->11434/tcp
sme_dashboard_api  Up 2 days       0.0.0.0:8400->8400/tcp
sme_dashboard_ui   Up 2 days       0.0.0.0:3030->3000/tcp
```
*Note: The `sme_app` port bounds claim of `8502:8501` can be verified by the presence of Streamlit executing inside.*

---

### 2. Verifying Configuration Keys (YAML vs Runtime)
**Goal:** Prove that a specific hyperparameter configuration is respected by the runtime engine (e.g. `api_polling_interval`).

**Command:**
```bash
python -c "
import yaml
with open('config/config.yaml', 'r') as f:
    conf = yaml.safe_load(f)
print(f\"Polling Interval YAML: {conf['system']['api_polling_interval']}\")
"
```
**Expected Output:**
```
Polling Interval YAML: 3
```

**Proof of utilization:**
Use grep to trace its dependency inside `dashboard/backend/db_reader.py`:
```bash
grep -n "api_polling_interval" dashboard/backend/db_reader.py
```
**Expected Output:**
```
82:    interval = config.get("system", {}).get("api_polling_interval", 3)
```

---

### 3. Proving a Hardcoded Literal Hazard
**Goal:** Verify a hardcoded literal (path or URL) directly invokes a runtime condition outside of the configuration boundaries.

**Command:**
```bash
grep -n "http://localhost:6333" dashboard/backend/db_reader.py
```
**Expected Output:**
```
12: QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
```
*Note: This specific literal was caught by the `generate_hardcoded.py` parser. The remediation requires enforcing the environment variable injection across all scripts preventing the hardcoded localhost fallback when running in a multi-node Swarm.*

---

### 4. Simulating Dynamic Feature Toggles
**Goal:** Prove the "Let AI Decide" parameter is hardcoded to `True` bypassing the external configuration bounds.

**Command:**
Execute a test query and inspect the RAG engine logs:
```bash
python -c "from src.retrieval.sequential_rag import SequentialRAG; r = SequentialRAG({'llm': None}); next(r.process_with_sections('test query', 'High', 'llama3', (5,10)))" 2>&1 | grep "Let AI Decide"
```
**Expected Output:**
```
[CONFIG] Let AI Decide: True | Depth: High | Paper Range: (5, 10)
```
*Correction: See `UNCONFIRMED_ITEMS.json`. The AI pipeline hardcodes this parameter on `sequential_rag.py:L454`.*
