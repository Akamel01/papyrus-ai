
import json

def repair_truncated_json(json_str: str) -> str:
    """
    Robustly repair a truncated JSON list by finding the last valid object closure.
    Uses a stack-based state machine to handle nested structures and strings correctly.
    """
    if not json_str.strip().startswith("["):
            return json_str

    # State machine
    depth = 0
    in_string = False
    escape = False
    last_valid_object_end = -1
    
    for i, char in enumerate(json_str):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 1: # We just closed a top-level object
                        last_valid_object_end = i
            elif char == '[':
                depth += 1
            elif char == ']':
                depth -= 1
    
    # If we are still deep or didn't close the list
    if depth > 0 or json_str.strip()[-1] != "]":
        if last_valid_object_end != -1:
            # Cut off after the last valid object and close the list
            # FIX POTENTIAL TRAILING COMMA: 
            # The cut happens at '}', so there shouldn't be a comma unless we include it.
            # json_str[:last_valid_object_end+1] includes '}'
            return json_str[:last_valid_object_end+1] + "]"
        else:
            # No valid objects found? Return empty list
            return "[]"
            
    return json_str

# Test Case from debug log
bad_json = """[
  {
    "source_label": "SOURCE_0",
    "citation": "doi:10.1016/j.trc.2012.10.001, 2012",      
    "claim_text": "No prior research has integrated statisti
"""
# Note: The debug log showed more, but let's test this minimal truncation.

print(f"Original: {bad_json!r}")
fixed = repair_truncated_json(bad_json)
print(f"Fixed:    {fixed!r}")

try:
    data = json.loads(fixed)
    print("✅ SUCCESS: Parsed JSON")
    print(data)
except Exception as e:
    print(f"❌ FAIL: {e}")
