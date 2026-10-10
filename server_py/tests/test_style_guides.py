"""注释风格映射测试：风格代码要翻译成模型可直接执行的格式说明。"""
from services.ai_comment_service import STYLE_GUIDES, describe_style


def test_known_styles_are_described():
    assert describe_style("jsdoc") == STYLE_GUIDES["jsdoc"]
    assert "JSDoc" in describe_style("jsdoc")
    assert "Docstring" in describe_style("docstring")
    assert describe_style("default") == STYLE_GUIDES["default"]


def test_unknown_style_falls_back_to_default():
    assert describe_style("") == STYLE_GUIDES["default"]
    assert describe_style("unknown-style") == STYLE_GUIDES["default"]


def test_style_code_is_case_insensitive():
    assert describe_style("JSDoc") == STYLE_GUIDES["jsdoc"]
    assert describe_style("  DocString  ") == STYLE_GUIDES["docstring"]
