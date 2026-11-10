import pytest

from src.services.ai_response_parser import (
    extract_ai_response_content,
    parse_ai_response_json,
    EmptyAIResponseError,
)


def test_parse_ai_response_json_uses_first_object_when_multiple_json_objects_are_concatenated():
    content = """```json
{"is_recommended": true, "reason": "first"}
{"is_recommended": false, "reason": "second"}
```"""

    result = parse_ai_response_json(content)

    assert result == {"is_recommended": True, "reason": "first"}


def test_parse_ai_response_json_extracts_json_from_wrapped_text():
    content = """分析結果如下：

```json
{"is_recommended": true, "reason": "wrapped"}
```

請按第一份結果處理。"""

    result = parse_ai_response_json(content)

    assert result == {"is_recommended": True, "reason": "wrapped"}


def test_parse_ai_response_json_raises_when_no_json_exists():
    with pytest.raises(ValueError):
        parse_ai_response_json("沒有任何 JSON 內容")


def test_extract_ai_response_content_with_none_content_but_valid_reasoning_content():
    """當 content 為 None 但 reasoning_content 有值時，應該成功提取 reasoning_content 的內容"""
    # 建立 mock 物件模擬 OpenAI 風格的響應
    message = type('Message', (), {
        'content': None,
        'reasoning_content': '這是推理內容'
    })()
    choice = type('Choice', (), {'message': message})()
    response = type('Response', (), {'choices': [choice]})()

    result = extract_ai_response_content(response)

    assert result == '這是推理內容'


def test_extract_ai_response_content_raises_when_content_and_reasoning_content_are_empty():
    """當 content 和 reasoning_content 都為空時，應該丟擲 EmptyAIResponseError"""
    # 建立 mock 物件
    message = type('Message', (), {
        'content': None,
        'reasoning_content': None
    })()
    choice = type('Choice', (), {'message': message})()
    response = type('Response', (), {'choices': [choice]})()

    with pytest.raises(EmptyAIResponseError):
        extract_ai_response_content(response)
