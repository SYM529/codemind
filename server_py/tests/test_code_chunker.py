"""项目级切片测试：符号边界、长度上限、无结构时的兜底。"""
from services import code_chunker, rag_service
from services.code_analyzer import analyze_code

PY_SOURCE = "\n".join([
    "import os",
    "",
    "",
    "def helper(a):",
    "    return a",
    "",
    "",
    "class Service:",
    "    def __init__(self):",
    "        self.value = 0",
    "",
    "    def run(self, x):",
    "        return x",
])

JS_SOURCE = "\n".join([
    "class Calculator {",
    "  add(x, y) {",
    "    return x + y;",
    "  }",
    "",
    "  sub(x, y) {",
    "    return x - y;",
    "  }",
    "}",
    "",
    "function standalone(z) {",
    "  return z;",
    "}",
])


def _analyze(code: str, language: str):
    structure = analyze_code(code, language)
    structure["totalLines"] = code.count("\n") + 1
    return structure


def _build(content, structure, **overrides):
    options = {"max_lines": 60, "overlap": 10, "max_chars": 4000}
    options.update(overrides)
    return code_chunker.build_chunks(content, structure, **options)


# --- 分块偏移（复用现有行窗口切分） ---


def test_chunk_content_with_offsets_reports_start_lines():
    content = "\n".join(f"line {index}" for index in range(100))
    pairs = rag_service.chunk_content_with_offsets(content, 40, 10)

    assert pairs[0][1] == 1
    assert pairs[1][1] == 31  # step = max_lines - overlap
    assert pairs[1][0].startswith("line 30")


# --- 符号边界 ---


def test_python_symbols_become_chunk_boundaries():
    chunks = _build(PY_SOURCE, _analyze(PY_SOURCE, "python"))
    names = {chunk["symbolName"] for chunk in chunks}

    assert names == {None, "helper", "Service", "__init__", "run"}

    preamble = next(chunk for chunk in chunks if chunk["symbolName"] is None)
    assert preamble["startLine"] == 1
    assert "import os" in preamble["content"]

    run_chunk = next(chunk for chunk in chunks if chunk["symbolName"] == "run")
    assert run_chunk["startLine"] == 12
    assert "return x" in run_chunk["content"]

    # 类声明行单独成块并归属到类名，不与方法内容重叠
    class_header = next(chunk for chunk in chunks if chunk["symbolName"] == "Service")
    assert class_header["content"].strip() == "class Service:"


def test_python_segments_are_contiguous_and_cover_all_lines():
    total = PY_SOURCE.count("\n") + 1
    segments = code_chunker.build_segments(_analyze(PY_SOURCE, "python"), total)

    assert segments[0][0] == 1
    assert segments[-1][1] == total
    for (_, previous_end, _), (next_start, _, _) in zip(segments, segments[1:]):
        assert next_start == previous_end + 1


def test_javascript_class_methods_are_segmented_without_end_lines():
    """JS 解析器给不出结束行，片段必须靠"下一个符号起始行"补齐且不重叠。"""
    total = JS_SOURCE.count("\n") + 1
    segments = code_chunker.build_segments(_analyze(JS_SOURCE, "javascript"), total)

    assert segments[0][0] == 1
    assert segments[-1][1] == total
    for (start, end, _), (next_start, _, _) in zip(segments, segments[1:]):
        assert end < next_start
        assert next_start == end + 1

    names = {name for _, _, name in segments if name}
    assert {"Calculator", "add", "sub", "standalone"} <= names


# --- 长度上限 ---


def test_long_function_is_split_into_bounded_chunks():
    body = "\n".join(f"    value_{index} = {index}" for index in range(200))
    source = "def big():\n" + body + "\n"
    structure = _analyze(source, "python")
    chunks = _build(source, structure, max_lines=60)

    assert len(chunks) >= 4
    assert all(chunk["symbolName"] == "big" for chunk in chunks)
    assert all(len(chunk["content"].split("\n")) <= 60 for chunk in chunks)
    starts = [chunk["startLine"] for chunk in chunks]
    assert starts == sorted(starts)
    assert starts[0] == 1
    # 切分必须覆盖到函数的真实结束行（AST 给出），不留下未索引的尾部
    assert max(chunk["endLine"] for chunk in chunks) == structure["functions"][0]["endLine"]


def test_single_line_content_is_split_by_characters():
    """压缩过的单行文件按行窗口切不动，必须有字符级兜底，保证 Chunk 长度有上界。"""
    content = "const big = '" + ("x" * 10_000) + "';"
    chunks = _build(content, None, max_chars=1000)

    assert len(chunks) == -(-len(content) // 1000)  # 向上取整
    assert all(len(chunk["content"]) <= 1000 for chunk in chunks)
    assert "".join(chunk["content"] for chunk in chunks) == content


def test_plain_text_without_structure_falls_back_to_line_windows():
    content = "\n".join(f"line {index}" for index in range(150))
    chunks = _build(content, None)

    assert len(chunks) >= 3
    assert all(chunk["symbolName"] is None for chunk in chunks)
    assert all(len(chunk["content"].split("\n")) <= 60 for chunk in chunks)
    assert chunks[0]["startLine"] == 1


def test_empty_content_produces_no_chunks():
    assert _build("", None) == []
    assert _build("   \n\n", {"functions": [], "classes": []}) == []
