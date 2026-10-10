from __future__ import annotations

import ast
import re
from typing import Any, Dict


def _js_analyze(code: str) -> Dict[str, Any]:
    """Fallback regex-based JS/TS analysis when no Babel is available."""
    structure: Dict[str, Any] = {
        "functions": [],
        "classes": [],
        "variables": [],
        "comments": [],
        "imports": [],
    }
    lines = code.split("\n")

    func_re = re.compile(
        r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)"
        r"|^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:\([^)]*\)\s*=>|\w+\s*=>)"
        r"|^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*function"
    )
    class_re = re.compile(r"^(?:export\s+)?class\s+(\w+)")
    import_re = re.compile(r"^import\s+|^const\s+\w+\s*=\s*require")
    var_re = re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)")

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        m = func_re.match(stripped)
        if m:
            name = m.group(1) or m.group(2) or m.group(3) or "anonymous"
            pm = re.search(r"\(([^)]*)\)", stripped)
            params = [p.strip().split(":")[0].split("=")[0] for p in pm.group(1).split(",") if p.strip()] if pm else []
            structure["functions"].append({"name": name, "line": i, "parameters": params})
            continue
        m = class_re.match(stripped)
        if m:
            structure["classes"].append({"name": m.group(1), "line": i})
            continue
        if import_re.match(stripped):
            structure["imports"].append({"statement": stripped, "line": i})
            continue
        m = var_re.match(stripped)
        if m:
            structure["variables"].append({"name": m.group(1), "line": i})

    seen_f = set()
    deduped_f = []
    for f in structure["functions"]:
        key = (f["name"], f["line"])
        if key not in seen_f:
            seen_f.add(key)
            deduped_f.append(f)
    structure["functions"] = deduped_f

    seen_v = set()
    deduped_v = []
    for v in structure["variables"]:
        key = (v["name"], v["line"])
        if key not in seen_v:
            seen_v.add(key)
            deduped_v.append(v)
    structure["variables"] = deduped_v

    return structure


def _py_analyze(code: str) -> Dict[str, Any]:
    structure: Dict[str, Any] = {
        "functions": [],
        "classes": [],
        "variables": [],
        "comments": [],
        "imports": [],
    }
    tree = ast.parse(code)
    lines = code.split("\n")

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            params = [a.arg for a in node.args.args]
            structure["functions"].append({"name": node.name, "line": node.lineno, "parameters": params})
        elif isinstance(node, ast.ClassDef):
            structure["classes"].append({"name": node.name, "line": node.lineno})
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    structure["variables"].append({"name": target.id, "line": node.lineno})
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            stmt = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
            structure["imports"].append({"statement": stmt, "line": node.lineno})

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item not in [
                    n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.lineno <= node.lineno
                ]:
                    params = [a.arg for a in item.args.args]
                    structure["functions"].append({"name": item.name, "line": item.lineno, "parameters": params})

    seen = set()
    deduped = []
    for f in structure["functions"]:
        key = (f["name"], f["line"])
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    structure["functions"] = deduped

    return structure


_JAVA_CONTROL_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "throw", "throws",
    "assert", "new", "super", "this", "else", "do", "try", "synchronized",
}
_JAVA_MODIFIER_WORDS = {
    "public", "protected", "private", "abstract", "static", "final",
    "synchronized", "native", "default", "strictfp",
}
_JAVA_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;")
_JAVA_CLASS_RE = re.compile(r"\b(class|interface|enum)\s+(\w+)")
_JAVA_METHOD_TAIL_RE = re.compile(r"^\s*(?:throws\s+[\w$.,\s]+)?[;{]?\s*$")
_JAVA_GENERIC_PREFIX_RE = re.compile(r"^<(?:[^<>]|<[^<>]*>)*>\s*")
_JAVA_FIELD_RE = re.compile(
    r"^(?:public|protected|private|static|final|volatile|transient|\s)+"
    r"(?:[\w$]+(?:\.[\w$]+)*(?:\s*<[^;=()]*>)?(?:\[\])?\s+)+(\w+)\s*[=;]"
)


def _java_logical_lines(code: str):
    """合并圆括号未闭合的跨行声明，返回 (起始行号, 合并后文本)。"""
    logical = []
    buf = ""
    buf_start = 1
    for i, raw in enumerate(code.split("\n"), 1):
        stripped = raw.strip()
        if not stripped:
            continue
        if not buf:
            buf_start = i
            buf = stripped
        else:
            buf = f"{buf} {stripped}"
        if buf.count("(") > buf.count(")"):
            continue
        logical.append((buf_start, buf))
        buf = ""
    if buf:
        logical.append((buf_start, buf))
    return logical


def _strip_java_annotations(line: str) -> str:
    previous = None
    while previous != line:
        previous = line
        line = re.sub(r"^@\w+(?:\([^)]*\))?\s*", "", line)
    return line


def _java_method_params(param_str: str) -> list[str]:
    params = []
    for part in param_str.split(","):
        cleaned = re.sub(r"@\w+(?:\([^)]*\))?", "", part)
        cleaned = cleaned.replace("final ", "").strip()
        if not cleaned:
            continue
        tokens = re.findall(r"\w+", cleaned)
        if tokens:
            params.append(tokens[-1])
    return params


def _java_analyze(code: str) -> Dict[str, Any]:
    """基于正则的 Java 结构分析：类/接口/枚举、方法（含构造器与泛型方法）、字段、import。"""
    structure: Dict[str, Any] = {
        "functions": [],
        "classes": [],
        "variables": [],
        "comments": [],
        "imports": [],
    }
    class_names = set()
    for i, raw in enumerate(code.split("\n"), 1):
        stripped = raw.strip()
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue
        m = _JAVA_IMPORT_RE.match(raw)
        if m:
            structure["imports"].append({"statement": stripped.rstrip(";"), "line": i})
            continue
        m = _JAVA_CLASS_RE.search(stripped)
        if m and "(" not in stripped:
            name = m.group(2)
            structure["classes"].append({"name": name, "line": i})
            class_names.add(name)

    for line_no, line in _java_logical_lines(code):
        if "(" not in line or ")" not in line:
            # 字段声明不含圆括号
            if re.match(r"^\s*(?:public|protected|private)\b", line):
                fm = _JAVA_FIELD_RE.match(line)
                if fm and not any(v["line"] == line_no for v in structure["variables"]):
                    structure["variables"].append({"name": fm.group(1), "line": line_no})
            continue
        if line.startswith("//") or line.startswith("*") or line.startswith("/*") or line.startswith("@"):
            line = _strip_java_annotations(line).strip()
            if not line or ")" not in line or line.startswith("//") or line.startswith("*"):
                continue
        close_paren = line.index(")")
        tail = line[close_paren + 1:]
        if not _JAVA_METHOD_TAIL_RE.match(tail):
            continue
        head = line[: line.index("(")].strip()
        head = _strip_java_annotations(head)
        tokens = head.split()
        if not tokens:
            continue
        if tokens[0].startswith("<"):
            head2 = _JAVA_GENERIC_PREFIX_RE.sub("", head)
            tokens = head2.split()
        while tokens and tokens[0] in _JAVA_MODIFIER_WORDS:
            tokens.pop(0)
        if tokens and tokens[0].startswith("<"):
            tokens = _JAVA_GENERIC_PREFIX_RE.sub("", " ".join(tokens)).split()
        if not tokens:
            continue
        if tokens[0] in _JAVA_CONTROL_KEYWORDS:
            continue
        param_str = line[line.index("(") + 1:close_paren]
        if len(tokens) == 1:
            # 无返回类型：仅构造器（方法名与类名相同）
            name = tokens[0]
            if name in class_names and re.match(r"^\w+$", name):
                structure["functions"].append(
                    {"name": name, "line": line_no, "parameters": _java_method_params(param_str)}
                )
            continue
        method_name = tokens[-1]
        return_type = " ".join(tokens[:-1])
        if not re.match(r"^\w+$", method_name):
            continue
        if return_type.split()[0] in _JAVA_CONTROL_KEYWORDS:
            continue
        if any(f["line"] == line_no for f in structure["functions"]):
            continue
        structure["functions"].append(
            {"name": method_name, "line": line_no, "parameters": _java_method_params(param_str)}
        )

    return structure


def analyze_code(code: str, language: str) -> Dict[str, Any]:
    if language in ("javascript", "typescript"):
        return _js_analyze(code)
    elif language == "python":
        return _py_analyze(code)
    elif language == "java":
        return _java_analyze(code)
    else:
        return _js_analyze(code)
