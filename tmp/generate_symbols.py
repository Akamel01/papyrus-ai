import ast
import os
import json
import re
from pathlib import Path

REPO_ROOT = Path(r"c:\gpt\SME")
TARGET_DIRS = ["src", "scripts", "app", "dashboard"]
OUTPUT_FILE = REPO_ROOT / "documentation" / "ENRICHED" / "SYSTEM_SYMBOLS_MAP.json"

def get_python_files(root_dir, dirs):
    py_files = []
    for d in dirs:
        target = root_dir / d
        if target.exists():
            for p in target.rglob("*.py"):
                if "__pycache__" not in str(p) and "tests" not in str(p):
                    py_files.append(p)
    return py_files

def extract_symbols_from_ast(filepath: Path):
    symbols = []
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(filepath))
        
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                symbols.append({
                    "name": node.name,
                    "type": "class",
                    "file": str(filepath.relative_to(REPO_ROOT)),
                    "start_line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "docstring": ast.get_docstring(node),
                })
                # Methods
                for sub_node in node.body:
                    if isinstance(sub_node, ast.FunctionDef):
                        symbols.append({
                            "name": sub_node.name,
                            "type": "method",
                            "parent": node.name,
                            "file": str(filepath.relative_to(REPO_ROOT)),
                            "start_line": sub_node.lineno,
                            "end_line": getattr(sub_node, "end_lineno", sub_node.lineno),
                            "docstring": ast.get_docstring(sub_node),
                        })
            elif isinstance(node, ast.FunctionDef):
                symbols.append({
                    "name": node.name,
                    "type": "function",
                    "file": str(filepath.relative_to(REPO_ROOT)),
                    "start_line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "docstring": ast.get_docstring(node),
                })
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        # Global constants typically uppercase
                        if target.id.isupper():
                            symbols.append({
                                "name": target.id,
                                "type": "global_variable",
                                "file": str(filepath.relative_to(REPO_ROOT)),
                                "start_line": node.lineno,
                                "end_line": getattr(node, "end_lineno", node.lineno),
                                "docstring": None,
                            })
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
    return symbols

def main():
    py_files = get_python_files(REPO_ROOT, TARGET_DIRS)
    all_symbols = []
    
    print(f"Parsing {len(py_files)} files...")
    for f in py_files:
        all_symbols.extend(extract_symbols_from_ast(f))
        
    print(f"Extracted {len(all_symbols)} symbols. Gathering usages...")
    
    # Pre-read all file contents for simple literal regex search
    file_contents = {str(f.relative_to(REPO_ROOT)): f.read_text(encoding="utf-8", errors="replace") for f in py_files}
    
    for sym in all_symbols:
        name = sym["name"]
        
        # Skip magic methods to avoid noise
        if name.startswith("__") and name.endswith("__"):
            sym["usages"] = []
            sym["status"] = "MAGIC_METHOD"
            continue
            
        usages = []
        # pattern to match whole word
        pattern = re.compile(r'\b' + re.escape(name) + r'\b')
        
        for fname, content in file_contents.items():
            for i, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    # Check if it's the definition itself
                    if fname == sym["file"]:
                        if sym["start_line"] <= i <= sym["end_line"]:
                            continue
                    usages.append(f"{fname}:{i}")
                    
        sym["usages"] = usages
        sym["status"] = "UNUSED" if len(usages) == 0 else "ACTIVE"
        
    os.makedirs(OUTPUT_FILE.parent, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_symbols, f, indent=2)
        
    print(f"Successfully wrote {len(all_symbols)} symbols to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
