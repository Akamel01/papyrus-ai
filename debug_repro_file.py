
from src.utils.json_parser import parse_llm_json
import logging

logging.basicConfig(level=logging.DEBUG)

file_path = "c:/gpt/SME/debug_librarian_fail.txt"
with open(file_path, "r", encoding="utf-8") as f:
    text = f.read()

print(f"--- TESTING PARSE ON FILE ({len(text)} chars) ---")
try:
    result = parse_llm_json(text, repair=True)
    print(f"SUCCESS. Result length: {len(result)}")
    print(f"First item: {result[0] if result else 'None'}")
except Exception as e:
    print(f"FAILURE. Error: {e}")
