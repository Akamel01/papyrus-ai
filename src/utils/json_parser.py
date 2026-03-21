"""
Centralized JSON parsing utility for LLM outputs.
Provides robust healing for truncated JSON, trailing commas, and markdown fences.
"""

import json
import re
import logging
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)

def parse_llm_json(
    text: str, 
    repair: bool = True, 
    log_errors: bool = True
) -> Any:
    """
    Parse a JSON string from an LLM response with robust error handling.
    
    Args:
        text: The raw string response from the LLM.
        repair: Whether to attempt to repair truncated/malformed JSON.
        log_errors: Whether to log parsing errors.
        
    Returns:
        The parsed Python object (list or dict).
        Returns empty list [] if input is None/Empty and cannot be parsed.
        
    Raises:
        json.JSONDecodeError: If parsing fails and repair is disabled or fails.
    """
    if not text:
        return []
        
    cleaned = text.strip()
    
    # 1. Strip Markdown Code Fences (Strict)
    # Handle ```json ... ``` or just ``` ... ```
    fence_pattern = r"```(?:\w+)?\s*(.*?)```"
    match = re.search(fence_pattern, cleaned, re.DOTALL)
    if match:
        cleaned = match.group(1).strip()
             
    # 2. Extract JSON start (if embedded in text)
    # Find the first '[' or '{'
    start_bracket = cleaned.find('[')
    start_brace = cleaned.find('{')
    
    if start_bracket != -1 and (start_brace == -1 or start_bracket < start_brace):
        # Starts with [ ( List )
        cleaned = cleaned[start_bracket:]
        # We don't enforce closing ] here because it might be truncated
    elif start_brace != -1:
        # Starts with { ( Dict )
        cleaned = cleaned[start_brace:]
    
    # 3. First Try: Standard Parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        if not repair:
            raise

    # 3. Repair: Truncation Healing (Stack Parser)
    repaired = _repair_json_structure(cleaned)
    
    # 4. Repair: Syntax Fix (Trailing Comma)
    # The stack parser usually handles the structure, but we might have a comma inside the structure
    # or the stack parser cut it off leaving a comma.
    # Simple regex for trailing commas in lists/dicts
    repaired = re.sub(r",\s*([\]}])", r"\1", repaired)
    
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        if log_errors:
            logger.error(f"Failed to parse LLM JSON after repair. Error: {e}")
            logger.debug(f"Repaired Text: {repaired[:500]}...")
        # Check if it was meant to be a list but failed completely
        if cleaned.strip().startswith("["):
             # If it looks like a list but failed, RAISE usage error to trigger logging in caller
             raise e
        raise e

def _repair_json_structure(json_str: str) -> str:
    """
    Robustly repair a truncated JSON list/object by finding the last valid closure.
    Uses a stack-based state machine.
    """
    cleaned = json_str.strip()
    
    # If it doesn't look like JSON, return as is (will fail parse)
    if not (cleaned.startswith("[") or cleaned.startswith("{")):
        return cleaned

    is_list = cleaned.startswith("[")
    
    # State machine
    depth = 0
    in_string = False
    escape = False
    last_valid_closure = -1
    
    for i, char in enumerate(cleaned):
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
                if depth == 0 or (depth == 1 and is_list): 
                     # Closed a top-level object (if dict) or element (if list)
                     # Actually, for list, depth=0 means closed LIST. depth=1 means inside list.
                     # We want to capture [ {obj}, {obj} ]
                     pass
            elif char == '[':
                depth += 1
            elif char == ']':
                depth -= 1
        
        # Track valid closure points
        # For a list: we want the position of the last '}' that brought depth to 1, OR the last ']' that ended it.
        if is_list:
            if char == '}' and depth == 1 and not in_string:
                last_valid_closure = i
            elif char == ']' and depth == 0 and not in_string:
                last_valid_closure = i
                return cleaned[:i+1] # It's valid!
        else: # Dictionary
             if char == '}' and depth == 0 and not in_string:
                 last_valid_closure = i
                 return cleaned[:i+1] # It's valid!

    # If truncated
    if last_valid_closure != -1:
        # We have at least one valid object
        # Cut after it
        truncated = cleaned[:last_valid_closure+1]
        print(f"DEBUG: Truncated at {last_valid_closure}: {truncated}")
        
        # If list, we need to close it
        if is_list:
             # If we cut at '}', we are inside the list, so append ']'
             # But check for trailing comma is handled by caller or simple strip
             if not truncated.endswith("]"):
                  print(f"DEBUG: Appending ] to {truncated}")
                  return truncated + "]"
        return truncated
    else:
        print("DEBUG: No valid closure found")
        # No valid objects found
        return "[]" if is_list else "{}"
