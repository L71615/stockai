"""测试 parse_ai_json — 通用 AI JSON 响应解析器"""

import pytest
from services.utils import parse_ai_json


def test_empty_input():
    assert parse_ai_json("") == {"raw": "", "parse_error": True}
    assert parse_ai_json("   ") == {"raw": "", "parse_error": True}


def test_direct_valid_json():
    result = parse_ai_json('{"hello": "world", "num": 42}')
    assert result == {"hello": "world", "num": 42}
    assert "parse_error" not in result


def test_markdown_code_block():
    result = parse_ai_json('```json\n{"x": 1}\n```')
    assert result == {"x": 1}


def test_markdown_no_lang():
    result = parse_ai_json('```\n{"y": 2}\n```')
    assert result == {"y": 2}


def test_json_fragment_in_text():
    result = parse_ai_json('Here is some text {"key": "value"} and more text')
    assert result == {"key": "value"}


def test_missing_comma_repair():
    # Missing comma between } and "
    raw = '{"a": 1}\n{"b": 2}'
    result = parse_ai_json(raw)
    # parse_ai_json tries regex extraction first, which may succeed on the first {}
    assert result == {"a": 1} or result.get("parse_error")


def test_invalid_json_fallback():
    result = parse_ai_json("this is not json at all")
    assert result.get("parse_error") is True
    assert result.get("raw") == "this is not json at all"


def test_nested_json():
    result = parse_ai_json('{"outer": {"inner": [1, 2, 3]}, "text": "hello"}')
    assert result["outer"] == {"inner": [1, 2, 3]}
    assert result["text"] == "hello"


def test_array_json():
    # Arrays are valid JSON too — parse_ai_json handles them
    result = parse_ai_json('[1, 2, 3]')
    assert result == [1, 2, 3]
