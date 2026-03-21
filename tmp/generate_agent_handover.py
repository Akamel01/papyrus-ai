import os
import ast
import re
from pathlib import Path

REPO_ROOT = Path(r"c:\gpt\SME")
OUTPUT_FILE = REPO_ROOT / "documentation" / "ENRICHED" / "COMPLETE_REPO_MAP.md"

def get_ast_info(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            tree = ast.parse(content)
            
            docstring = ast.get_docstring(tree) or "No module docstring provided."
            
            classes = []
            functions = []
            prompts = []
            sql_schemas = []
            
            # Find prompts and schemas with regex for raw text scanning
            for match in re.finditer(r'(?i)(prompt|template|sys_msg)\s*=\s*f?[\'"]{3}([\s\S]*?)[\'"]{3}', content):
                prompts.append((match.group(1), match.group(2)[:200] + "... [TRUNCATED]"))
                
            for match in re.finditer(r'(?i)CREATE\s*TABLE\s*(IF\s*NOT\s*EXISTS)?\s*([a-zA-Z_]+)\s*\(([\s\S]*?)\)', content):
                sql_schemas.append((match.group(2), match.group(3).strip()))

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                    classes.append((node.name, methods))
                elif isinstance(node, ast.FunctionDef) and getattr(node, "col_offset", 0) == 0:
                    functions.append(node.name)
                    
            return docstring, classes, functions, prompts, sql_schemas
    except Exception as e:
        return f"Parse error: {str(e)}", [], [], [], []

def main():
    map_lines = [
        "# COMPLETE REPOSITORY & DATA MODEL MAP",
        "> **Notice to AI Agents:** This document is your zero-context handover blueprint. Use it to instantly locate any database schema, prompt logic, API endpoint, or pipeline orchestrator **without** spending context tokens searching the directory tree.",
        ""
    ]
    
    directories_to_scan = ["app", "config", "dashboard", "scripts", "src"]
    
    all_schemas = []
    all_prompts = []
    
    # Render Directory Map
    map_lines.append("## 1. Directory Anatomy & Script Responsibilities")
    
    for d in directories_to_scan:
        target_dir = REPO_ROOT / d
        if not target_dir.exists(): continue
        
        map_lines.append(f"### `/{d}` Namespace")
        for root, _, files in os.walk(target_dir):
            if "__pycache__" in root or "node_modules" in root or "/dist" in root or "/build" in root: continue
            
            rel_root = os.path.relpath(root, REPO_ROOT)
            if ".git" in rel_root: continue
            
            py_files = sorted([f for f in files if f.endswith(".py")])
            if not py_files: continue
            
            map_lines.append(f"#### Directory: `{rel_root}`")
            for pyf in py_files:
                fp = Path(root) / pyf
                docstring, classes, func, prompts, sql = get_ast_info(fp)
                
                # Add to glob lists
                for p_name, p_val in prompts:
                    all_prompts.append(f"- **File:** `{rel_root}/{pyf}`\n  - **Variable:** `{p_name}`\n  - **Preview:** `{p_val.replace(chr(10), ' ')}`")
                for s_name, s_val in sql:
                    all_schemas.append(f"**Table:** `{s_name}` (from `{rel_root}/{pyf}`)\n```sql\nCREATE TABLE {s_name} ({s_val})\n```")
                
                # Format listing
                class_str = ", ".join([f"{c[0]}({len(c[1])} methods)" for c in classes]) if classes else "None"
                func_str = ", ".join(func[:5]) + ("..." if len(func) > 5 else "") if func else "None"
                
                map_lines.append(f"- **`{pyf}`**")
                map_lines.append(f"  - *Purpose:* {docstring.split(chr(10))[0][:150]}")
                map_lines.append(f"  - *Classes Defined:* {class_str}")
                map_lines.append(f"  - *Global Functions:* {func_str}")
            map_lines.append("")

    # Render Schemas
    map_lines.append("## 2. Database Schemas (SQLite/Postgres equivalent)")
    if all_schemas:
        map_lines.extend(all_schemas)
    else:
        map_lines.append("*No strict raw SQL CREATE TABLE statements detected.*")
    map_lines.append("")

    # Render Prompts
    map_lines.append("## 3. LLM Interaction Prompts & Templates")
    if all_prompts:
        map_lines.extend(all_prompts)
    else:
        map_lines.append("*No raw multi-line prompt structures detected natively.*")
        
    # Render Qdrant Payload Notes based on SME knowledge
    map_lines.append("## 4. Qdrant Vector DB Assumed Payload Metadata")
    map_lines.append("Based on the semantic streaming ingestion pipeline, Qdrant heavily leverages the following metadata dictionary structures per tensor chunk:")
    map_lines.append("""```json
{
  "doi": "10.xxxx/yyyy",
  "chunk_id": "c_12345",
  "text": "The raw chunk text extracted via PyMuPDF limit.",
  "apa_reference": "Hardbound string generated by PaperDiscoverer natively.",
  "page": 5,
  "depth_tier": "High"
}
```""")

    # Write out
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(map_lines))
        
    print(f"Generated complete handover map to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
