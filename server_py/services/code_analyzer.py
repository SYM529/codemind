from __future__ import annotations

import ast
import re
from typing import Any, Dict, List, Optional

# JS/TS 类声明；用于类体方法识别，比原有行首正则多容忍 default 导出
_JS_CLASS_DECL_RE = re.compile(r"^(?:export\s+)?(?:default\s+)?class\s+(\w+)")
# 类体中的成员方法：static/async/get/set/私有字段均可
_JS_METHOD_RE = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?(#?[A-Za-z_$][\w$]*)\s*\("
)
# 这些关键字后面的括号不是方法声明
_JS_CONTROL_WORDS = frozenset({
    "if", "for", "while", "switch", "catch", "return", "do", "else", "with",
    "function", "typeof", "new", "delete", "await", "case", "throw", "super", "this", "in", "of",
})


def _js_param_names(text: str) -> List[str]:
    """从形如 ``foo(a, b = 1, c: string)`` 的片段中提取参数名。"""
    match = re.search(r"\(([^)]*)\)", text)
    if not match:
        return []
    return [
        part.strip().split(":")[0].split("=")[0]
        for part in match.group(1).split(",")
        if part.strip()
    ]


def _count_braces(line: str) -> int:
    """粗略统计一行中大括号的净增减。

    跳过行注释、单引号/双引号/模板字符串内容，避免 ``const s = "}";`` 这类
    字面量把深度算错（正则解析器不需要也不应该做到完全精确）。
    """
    depth = 0
    index = 0
    quote: Optional[str] = None
    while index < len(line):
        char = line[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'`":
            quote = char
        elif char == "/" and index + 1 < len(line) and line[index + 1] == "/":
            break
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    return depth


def _js_class_methods(lines: List[str]) -> List[Dict[str, Any]]:
    """识别类体内的成员方法。

    只有"行起始深度恰好等于类体深度"的行才会被判定为方法，
    因此方法体内部的 if/for 等控制语句不会因为缩进被误判成方法。
    单行写完整个类（``class A { foo() {} }``）等极端写法识别不到，
    这类文件在项目索引里会退化为按行窗口切片。
    """
    methods: List[Dict[str, Any]] = []
    depth = 0
    class_body_depths: List[int] = []
    pending_class_depth: Optional[int] = None

    for number, raw in enumerate(lines, 1):
        stripped = raw.strip()
        start_depth = depth

        if class_body_depths and start_depth == class_body_depths[-1]:
            match = _JS_METHOD_RE.match(stripped)
            if match and match.group(1) not in _JS_CONTROL_WORDS:
                methods.append({
                    "name": match.group(1),
                    "line": number,
                    "parameters": _js_param_names(stripped),
                })

        delta = _count_braces(raw)
        depth += delta
        if _JS_CLASS_DECL_RE.match(stripped):
            if delta > 0:
                class_body_depths.append(start_depth + 1)
            else:
                # ``class A`` 换行后才写 ``{``：等深度真正增加时再登记类体深度
                pending_class_depth = start_depth
        elif pending_class_depth is not None and depth > pending_class_depth:
            class_body_depths.append(depth)
            pending_class_depth = None

        while class_body_depths and depth < class_body_depths[-1]:
            class_body_depths.pop()

    return methods


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
    import_re = re.compile(r"^import\s+|^const\s+\w+\s*=\s*require")
    var_re = re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)")

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        m = func_re.match(stripped)
        if m:
            name = m.group(1) or m.group(2) or m.group(3) or "anonymous"
            structure["functions"].append({"name": name, "line": i, "parameters": _js_param_names(stripped)})
            continue
        m = _JS_CLASS_DECL_RE.match(stripped)
        if m:
            structure["classes"].append({"name": m.group(1), "line": i})
            continue
        if import_re.match(stripped):
            structure["imports"].append({"statement": stripped, "line": i})
            continue
        m = var_re.match(stripped)
        if m:
            structure["variables"].append({"name": m.group(1), "line": i})

    # 类体内的成员方法：行首正则覆盖不到，单独按大括号深度补一轮
    structure["functions"].extend(_js_class_methods(lines))

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


def _py_symbol(node) -> Dict[str, Any]:
    """Python 函数节点 → 结构条目。

    额外带上 ``endLine``：AST 能给出精确结束行，项目级切片据此按函数边界切割，
    不依赖"下一个符号起始行减一"的估算。
    """
    return {
        "name": node.name,
        "line": node.lineno,
        "endLine": getattr(node, "end_lineno", None),
        "parameters": [arg.arg for arg in node.args.args],
    }


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
            structure["functions"].append(_py_symbol(node))
        elif isinstance(node, ast.ClassDef):
            structure["classes"].append({
                "name": node.name,
                "line": node.lineno,
                "endLine": getattr(node, "end_lineno", None),
            })
            # 类方法：历史实现只收集"函数体内嵌套的函数"，类体中的方法整体缺失，
            # 项目级切片会因此把整个类当作一段文本，这里补齐
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    structure["functions"].append(_py_symbol(item))
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
                    structure["functions"].append(_py_symbol(item))

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
