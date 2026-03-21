import ast
import os
import csv
import re
from pathlib import Path

REPO_ROOT = Path(r"c:\gpt\SME")
OUTPUT_FILE = REPO_ROOT / "documentation" / "ENRICHED" / "HARDCODED_LITERALS.csv"

# Patterns to flag as potentially dangerous hardcoded literals
IP_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
URL_PATTERN = re.compile(r'https?://[^\s\'"]+')
PORT_PATTERN = re.compile(r'port\s*=\s*([0-9]{4,5})', re.IGNORECASE)
PATH_PATTERN = re.compile(r'(/data/|/app/|C:\\)')
SECRET_PATTERN = re.compile(r'(api[_\-]?key|secret|token|password)[_\-]?\w*\s*=\s*[\'"]([^\'"]+)[\'"]', re.IGNORECASE)

def scan_file_for_literals(filepath: Path):
    findings = []
    try:
        content = filepath.read_text(encoding="utf-8")
        lines = content.splitlines()
        
        # We will use simple regex over lines instead of AST for strings 
        # because AST Literal visits can be overwhelmingly noisy 
        # (every single string in the codebase).
        for i, line in enumerate(lines, 1):
            if line.strip().startswith('#'):
                continue # skip comments
                
            # Check IPs
            for match in IP_PATTERN.finditer(line):
                val = match.group()
                if val not in ("127.0.0.1", "0.0.0.0"):
                    findings.append((val, "Hardcoded IP", f"{filepath.relative_to(REPO_ROOT)}:{i}"))
                else:
                    findings.append((val, "Localhost binding", f"{filepath.relative_to(REPO_ROOT)}:{i}"))
                    
            # Check URLs
            for match in URL_PATTERN.finditer(line):
                val = match.group()
                if "localhost" not in val and "test" not in val:
                    findings.append((val, "Hardcoded URL/Endpoint", f"{filepath.relative_to(REPO_ROOT)}:{i}"))
                    
            # Check Absolute Paths
            for match in PATH_PATTERN.finditer(line):
                val = match.group()
                findings.append((val, "Absolute System Path", f"{filepath.relative_to(REPO_ROOT)}:{i}"))
                
            # Check Secrets/Tokens
            for match in SECRET_PATTERN.finditer(line):
                val = match.group(2)
                findings.append((val, "Hardcoded Secret/Token", f"{filepath.relative_to(REPO_ROOT)}:{i}"))
                
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    return findings

def main():
    py_files = []
    for d in ["src", "scripts", "dashboard", "app"]:
        target = REPO_ROOT / d
        if target.exists():
            for p in target.rglob("*.py"):
                if "__pycache__" not in str(p) and "test" not in p.name:
                    py_files.append(p)
                    
    all_findings = []
    for f in py_files:
        all_findings.extend(scan_file_for_literals(f))
        
    os.makedirs(OUTPUT_FILE.parent, exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Literal Value", "Hazard Type", "Location", "Impact", "Suggested Remediation"])
        for val, hazard, loc in all_findings:
            # Generate default impact and remediation
            impact = "Prevents multi-environment portability and creates security boundaries risks."
            remediation = "Move to config/*.yaml or load via os.environ.get()"
            writer.writerow([val, hazard, loc, impact, remediation])
            
    print(f"Found {len(all_findings)} hardcoded literals. Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
