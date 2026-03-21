
import pytest
from src.utils.json_parser import parse_llm_json

def test_parse_valid_json():
    text = '[{"id": 1, "val": "test"}]'
    result = parse_llm_json(text)
    assert len(result) == 1
    assert result[0]["id"] == 1

def test_parse_markdown_fences():
    text = """
    Here is the data:
    ```json
    [
        {"id": 1}
    ]
    ```
    """
    result = parse_llm_json(text)
    assert len(result) == 1
    assert result[0]["id"] == 1

def test_parse_truncated_list_simple():
    # Truncated after first object
    text = '[{"id": 1}, {"id": 2'
    result = parse_llm_json(text)
    assert len(result) == 1
    assert result[0]["id"] == 1

def test_parse_truncated_list_trailing_comma():
    # Truncated after comma
    text = '[{"id": 1}, '
    result = parse_llm_json(text)
    assert len(result) == 1
    assert result[0]["id"] == 1

def test_parse_truncated_inside_string():
    # Truncated inside a string in the first object
    text = '[{"id": 1, "text": "This is going to be cu'
    # Should return empty list because no valid object was closed
    result = parse_llm_json(text)
    assert result == []

def test_parse_truncated_nested():
    # Nested structure
    text = '[{"id": 1, "data": {"a": 1}}, {"id": 2, "data": {'
    result = parse_llm_json(text)
    assert len(result) == 1
    assert result[0]["id"] == 1
    assert result[0]["data"]["a"] == 1

def test_parse_trailing_comma_syntax():
    # Explicit trailing comma (syntax error in standard JSON)
    text = '[{"id": 1},]'
    result = parse_llm_json(text)
    assert len(result) == 1

def test_parse_none_or_empty():
    assert parse_llm_json(None) == []
    assert parse_llm_json("") == []

def test_garbage_input():
    # Should raise error or return empty? Implementation raises JSONDecodeError if check fails
    with pytest.raises(Exception): # catch JSONDecodeError
        parse_llm_json("This is just random text")
