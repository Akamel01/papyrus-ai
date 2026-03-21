
from src.utils.json_parser import parse_llm_json
import logging

# Setup basic logging to see debug prints
logging.basicConfig(level=logging.DEBUG)

truncated_text = """[
  {
    "source_label": "SOURCE_0",
    "citation": "Anonymous, 2016",
    "claim_text": "Claim 1",
    "excerpt_quote": "Quote 1",
    "methodology_type": "empirical",
    "methodology_context": "Ctx 1",
    "topics": ["t1"],
    "certainty": "high",
    "year": 2016
  },
  {
    "source_label": "SOURCE_1",
    "citation": "Incomplete Citation, 20"""

print("--- TESTING TRUNCATION REPAIR ---")
try:
    result = parse_llm_json(truncated_text, repair=True)
    print(f"SUCCESS. Result length: {len(result)}")
    print(f"Content: {result}")
except Exception as e:
    print(f"FAILURE. Error: {e}")
