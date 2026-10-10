import pytest

from services.ai_comment_service import _normalize, _parse_json_response


def test_parse_plain_json():
    assert _parse_json_response('{"summary": "ok"}')["summary"] == "ok"


def test_parse_fenced_json():
    text = '```json\n{"summary": "ok"}\n```'
    assert _parse_json_response(text)["summary"] == "ok"


def test_parse_array_json():
    parsed = _parse_json_response('[{"functionName": "a", "line": 1}]')
    assert isinstance(parsed, list)


def test_parse_json_with_surrounding_text():
    text = 'Here is the result:\n{"summary": "ok"}\nThanks.'
    assert _parse_json_response(text)["summary"] == "ok"


def test_parse_invalid_raises():
    with pytest.raises(Exception):
        _parse_json_response("not json at all")


def test_normalize_accepts_top_level_array():
    result = _normalize([{"functionName": "add", "line": 1, "comment": "/** add */"}])
    assert len(result.comments) == 1
    assert result.comments[0].functionName == "add"


def test_normalize_coerces_line_and_params():
    result = _normalize({"comments": [{"name": "f", "line": "3", "parameters": ["a"]}]})
    assert result.comments[0].line == 3
    assert result.comments[0].parameters[0].name == "a"
