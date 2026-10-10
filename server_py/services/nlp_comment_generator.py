"""Rule-based (non-AI) comment generator, ported from the original Node implementation."""
from __future__ import annotations

import re
from typing import Any, Dict, List


def _camel_to_words(name: str) -> List[str]:
    return [w for w in re.split(r"[_\-\s]+|(?=[A-Z])", name) if w]


def _generate_function_description(name: str) -> str:
    words = _camel_to_words(name)
    verbs = {"get", "set", "add", "create", "update", "delete", "remove", "fetch",
             "load", "save", "send", "build", "make", "calc", "calculate", "parse",
             "format", "validate", "handle", "process", "render", "init"}
    nouns = [w for w in words if w.lower() not in verbs]
    for w in words:
        if w.lower() in verbs:
            return f"执行{w}操作"
    if nouns:
        return f"处理{nouns[0]}相关功能"
    return "执行特定功能"


def _generate_param_description(param: str) -> str:
    words = _camel_to_words(param)
    return f"{words[0]}参数" if words else "输入参数"


def _generate_return_description(name: str) -> str:
    words = _camel_to_words(name)
    nouns = [w for w in words if w.lower() not in {"get", "set", "add", "create", "update", "delete"}]
    return f"{nouns[0]}结果" if nouns else "操作结果"


def generate_function_comment(function_info: dict, language: str) -> str:
    name = function_info.get("name", "anonymous")
    parameters = function_info.get("parameters", []) or []
    desc = _generate_function_description(name)

    if language in ("javascript", "typescript"):
        params = "".join(f"\n * @param {{*}} {p} - {_generate_param_description(p)}" for p in parameters)
        return f"/**\n * {desc}\n *{params}\n * @returns {{*}} {_generate_return_description(name)}\n */"
    if language == "python":
        args = "".join(f"\n    {p}: {_generate_param_description(p)}" for p in parameters)
        return f'"""\n{desc}\n{args}\n\nReturns:\n    {_generate_return_description(name)}\n"""'
    if language == "java":
        params = "".join(f"\n * @param {p} {_generate_param_description(p)}" for p in parameters)
        return f"/**\n * {desc}\n *{params}\n * @return {_generate_return_description(name)}\n */"
    return ""


def build_comments(structure: Dict[str, Any], language: str) -> List[Dict[str, Any]]:
    comments = []
    for func in structure.get("functions", []):
        comments.append({
            "line": func.get("line", 1),
            "functionName": func.get("name", "anonymous"),
            "comment": generate_function_comment(func, language),
        })
    return comments
