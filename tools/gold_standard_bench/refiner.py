
"""
Refiner Agent.

This module handles the "Self-Correction" phase.
It reads source code, generates patches, and applies them safely.
"""

import os
import shutil
import logging
import time
import re
from pathlib import Path
from typing import Dict, Optional

from src.core.interfaces import LLMClient

logger = logging.getLogger(__name__)

TWEAKABLE_CONFIGS = """
SYSTEM PARAMETERS & THRESHOLDS (Adjust these instead of rewriting logic if possible):

1. RESEARCH DEPTH (`src/config/depth_presets.py`)
   - High Depth (Default): {
       "min_unique_papers": 50,
       "top_k_final": 100,
       "max_tokens": 10500,
       "temperature": 0.05
     }
   - Medium Depth: { "min_unique_papers": 25, "temperature": 0.1 }

2. GLOBAL THRESHOLDS (`src/config/thresholds.py`)
   - CONFIDENCE_THRESHOLDS: HIGH >= 10 unique papers, MEDIUM >= 5.
   - SEQUENTIAL_FORCE_FOLLOWUP_THRESHOLD: 8 papers (Triggers follow-up search).
   - CONTEXT_SIMILARITY_THRESHOLD: 0.8 (Deduplication).

3. ENGINE CONSTRAINTS (`src/academic_v2/engine.py`)
   - _CITATION_CONSTRAINT: Mandates [^X] & APA bibliography.
   - _ANALYTICAL_CONSTRAINT: Mandates comparison of conflict-based vs. crash-based.
"""

class CodeRefiner:
    """
    The Surgeon. Modifies code to fix compliance issues.
    """
    
    def __init__(self, llm_client: LLMClient, project_root: str, model_name: str = "gpt-oss:120b-cloud", log_file: Optional[Path] = None):
        self.llm = llm_client
        self.root = Path(project_root)
        self.model_name = model_name
        self.log_file = log_file
        self.backup_dir = self.root / "backup"
        
    def _read_recent_logs(self, max_lines: int = 200) -> str:
        """Read the last N lines of the log file for context."""
        if not self.log_file or not self.log_file.exists():
            return "NO LOGS FOUND."
            
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                return "".join(lines[-max_lines:])
        except Exception as e:
            return f"ERROR READING LOGS: {e}"

    def create_backup(self) -> str:
        """Create a timestamped backup of the src directory."""
        if not self.backup_dir.exists():
            self.backup_dir.mkdir()
            
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"src_backup_{timestamp}"
        
        src_path = self.root / "src"
        if src_path.exists():
            shutil.copytree(src_path, backup_path)
            logger.info(f"🛡️ Backup created at: {backup_path}")
            return str(backup_path)
        return ""

    def identify_target_file(self, issue: str) -> str:
        """
        Map the failure criterion to the responsible file.
        Prioritizes configuration files for tuneable issues.
        """
        issue_lower = issue.lower()
        
        # 1. Check for Configuration/Threshold targets first
        if any(x in issue_lower for x in ["count", "quantity", "number of papers", "token limit", "research depth", "depth level"]):
            return "src/config/depth_presets.py"
            
        if any(x in issue_lower for x in ["confidence", "threshold", "follow-up", "deduplication"]):
            return "src/config/thresholds.py"

        # 2. Check for Persona/Logic targets
        if any(x in issue_lower for x in ["authority", "currency", "methodology"]):
            return "src/academic_v2/librarian.py" # Or engine triggers
        elif any(x in issue_lower for x in ["organization", "gap", "alignment", "balance"]):
            return "src/academic_v2/architect.py"
        elif any(x in issue_lower for x in ["analysis", "synthesis", "precision", "tone"]):
            return "src/academic_v2/drafter.py"
            
        return "src/academic_v2/engine.py" # Default fallback
        
    def generate_patch(self, issue: str, feedback: str, target_file_rel: str) -> Optional[str]:
        """
        Ask LLM to generate a python code patch.
        We ask for the WHOLE NEW FILE CONTENT to be safe, or a robust replacement block.
        For reliability, let's ask for specific prompt variables to update.
        """
        target_path = self.root / target_file_rel
        if not target_path.exists():
            logger.error(f"Target file not found: {target_path}")
            return None
            
        with open(target_path, "r", encoding="utf-8") as f:
            code_content = f.read()
            
        # Get Log Context
        log_snippet = self._read_recent_logs()
            
        prompt = f"""CODE REFINEMENT TASK
        
ISSUE: The output failed the criterion: "{issue}".
FEEDBACK: "{feedback}"
TARGET FILE: `{target_file_rel}`

RELEVANT LOGS (LAST 200 LINES):
```
{log_snippet}
```

{TWEAKABLE_CONFIGS}

TASK: Rewrite the code to fix the issue.
- If this is a CONFIGURATION file (`depth_presets.py`, `thresholds.py`), adjust the values based on the feedback (e.g., increase `min_unique_papers` if coverage is low).
- If this is a LOGIC file, update the prompt templates or constraints.
- ANALYZE THE LOGS: If you see runtime errors (e.g., "Connection refused", "KeyError"), FIX THEM in the code.

CURRENT CODE:
```python
{code_content}
```

INSTRUCTIONS:
1. Return the COMPLETE UPDATED CODE for the file.
2. Do not remove any existing functionality unless it conflicts with the fix.
3. If tuning parameters, be conservative (e.g. increase by 20-50%, not 10x).

OUTPUT FORMAT:
Return ONLY the python code block.
"""
        try:
            response = self.llm.generate(
                prompt=prompt,
                system_prompt="You are a Senior Python Engineer. Rewrite the code to fix the prompt logic and runtime errors.",
                temperature=0.0,
                max_tokens=8000, # Large buffer for full file
                model=self.model_name
            )
            
            # Extract code
            code = response
            if "```python" in code:
                code = code.split("```python")[1].split("```")[0]
            elif "```" in code:
                code = code.split("```")[1].split("```")[0]
                
            return code.strip()
            
        except Exception as e:
            logger.error(f"Patch generation failed: {e}")
            return None

    def apply_patch(self, new_content: str, target_file_rel: str) -> bool:
        """Write the new content to file."""
        try:
            # 1. Backup first
            self.create_backup()
            
            # 2. Write
            target_path = self.root / target_file_rel
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(new_content)
                
            logger.info(f"💉 Patch applied to {target_file_rel}")
            return True
        except Exception as e:
            logger.error(f"Applying patch failed: {e}")
            return False
