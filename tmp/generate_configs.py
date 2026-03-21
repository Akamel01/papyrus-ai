import yaml
import re
import csv
import os
from pathlib import Path

REPO_ROOT = Path(r"c:\gpt\SME")
OUTPUT_FILE = REPO_ROOT / "documentation" / "ENRICHED" / "CONFIG_MAP.csv"

def flatten_dict(d, parent_key='', sep='.'):
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)

def main():
    # 1. Load Defined Configs
    defined_keys = {}
    config_dir = REPO_ROOT / "config"
    for yaml_file in config_dir.glob("*.yaml"):
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    flat = flatten_dict(data)
                    for k, v in flat.items():
                        defined_keys[k] = {"file": yaml_file.name, "default": str(v)}
        except Exception as e:
            print(f"Error parsing {yaml_file}: {e}")
            
    # 2. Scan Python Code
    py_files = []
    for d in ["src", "scripts", "dashboard", "app"]:
        target = REPO_ROOT / d
        if target.exists():
            for p in target.rglob("*.py"):
                if "__pycache__" not in str(p) and "test" not in p.name:
                    py_files.append(p)
                    
    # Look for config.get("key"), os.environ.get("key"), config["key"]
    code_keys = {}
    pattern = re.compile(r'(?:config|os\.environ|environ|os\.getenv)\.get\([\'"]([a-zA-Z0-9_\.]+)[\'"]')
    pattern_bracket = re.compile(r'config\[[\'"]([a-zA-Z0-9_\.]+)[\'"]\]')
    
    for f in py_files:
        try:
            content = f.read_text(encoding="utf-8")
            for i, line in enumerate(content.splitlines(), 1):
                loc = f"{f.relative_to(REPO_ROOT)}:{i}"
                for m in pattern.finditer(line):
                    key = m.group(1)
                    if key not in code_keys: code_keys[key] = []
                    code_keys[key].append(loc)
                for m in pattern_bracket.finditer(line):
                    key = m.group(1)
                    if key not in code_keys: code_keys[key] = []
                    code_keys[key].append(loc)
        except:
            pass
            
    # 3. Output results
    os.makedirs(OUTPUT_FILE.parent, exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Key", "Status", "Defined In", "Default Value", "Usages", "Issue"])
        
        all_unique_keys = set(defined_keys.keys()) | set(code_keys.keys())
        for k in sorted(all_unique_keys):
            defined = defined_keys.get(k, {})
            usages = code_keys.get(k, [])
            
            status = "OK"
            issue = ""
            
            if not defined and usages:
                status = "MISSING_IN_CONFIG"
                issue = "Key is requested by codebase but absent in YAML defaults."
            elif defined and not usages:
                status = "UNUSED_CONFIG"
                issue = "Key is in YAML defaults but never read in Python code."
                
            writer.writerow([
                k, 
                status, 
                defined.get("file", "N/A"), 
                defined.get("default", "N/A"), 
                " | ".join(usages), 
                issue
            ])
            
    print(f"Config mapping complete. Tracked {len(all_unique_keys)} keys. Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
