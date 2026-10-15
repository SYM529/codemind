"""把源码按符号（类/函数）边界切片。

切片策略（从粗到细，逐级兜底）：

1. 有结构信息时，按符号边界切；嵌套符号（类里的方法）递归细分，
   类中不属于任何方法的行（类声明行、字段）单独成段并归属到类名；
2. 单个符号仍超过上限时，复用 ``rag_service.chunk_content_with_offsets`` 做带重叠的行窗口切分；
3. 单行仍然超长（压缩过的 JS 等）时，按字符硬切，保证 Chunk 长度有上界。

不依赖新的解析器：结构信息完全来自现有的 ``code_analyzer.analyze_code``。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services import rag_service

logger = logging.getLogger(__name__)


def _collect_spans(structure: Dict[str, Any], total_lines: int) -> List[Dict[str, Any]]:
    """把结构分析结果整理成 (name, start, end) 区间。

    ``endLine`` 只有 Python（真实 AST）会给出；其余语言缺失时用
    "下一个符号起始行 - 1" 补齐，因此不会出现区间重叠。
    """
    spans: List[Dict[str, Any]] = []
    for key in ("classes", "functions"):
        for item in structure.get(key) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            start = item.get("line")
            if not name or not isinstance(start, int) or start < 1:
                continue
            end = item.get("endLine")
            if not isinstance(end, int) or end < start:
                end = None
            spans.append({"name": name, "start": min(start, total_lines), "end": end})

    spans.sort(key=lambda s: (s["start"], s["end"] if s["end"] is not None else total_lines))
    for index, span in enumerate(spans):
        if span["end"] is None:
            following = spans[index + 1]["start"] if index + 1 < len(spans) else total_lines + 1
            span["end"] = min(following - 1, total_lines)
    return spans


def _is_contained(inner: Dict[str, Any], outer: Dict[str, Any]) -> bool:
    return (
        inner is not outer
        and outer["start"] <= inner["start"]
        and inner["end"] <= outer["end"]
    )


def _segment(spans: List[Dict[str, Any]], start: int, end: int, name: Optional[str],
             out: List[tuple]) -> None:
    """把 [start, end] 按落在其内部的符号递归细分，结果追加到 out。"""
    children = [
        span for span in spans
        if span["start"] >= start and span["end"] <= end and not (span["start"] == start and span["end"] == end)
    ]
    outermost: List[Dict[str, Any]] = []
    for child in sorted(children, key=lambda s: s["start"]):
        if outermost and child["start"] <= outermost[-1]["end"]:
            continue
        outermost.append(child)

    cursor = start
    for child in outermost:
        if child["start"] > cursor:
            out.append((cursor, child["start"] - 1, name))
        _segment(spans, child["start"], child["end"], child["name"], out)
        cursor = child["end"] + 1
    if cursor <= end:
        out.append((cursor, end, name))


def build_segments(structure: Dict[str, Any], total_lines: int) -> List[tuple]:
    """返回按行号连续、互不重叠的 ``[(start, end, symbol_name)]``。"""
    if total_lines < 1:
        return []
    spans = _collect_spans(structure, total_lines)
    roots = [span for span in spans if not any(_is_contained(span, other) for other in spans)]

    segments: List[tuple] = []
    cursor = 1
    for root in sorted(roots, key=lambda s: s["start"]):
        if root["start"] > cursor:
            segments.append((cursor, root["start"] - 1, None))
        _segment(spans, root["start"], root["end"], root["name"], segments)
        cursor = root["end"] + 1
    if cursor <= total_lines:
        segments.append((cursor, total_lines, None))
    return [(start, end, name) for start, end, name in segments if end >= start]


def _split_by_chars(text: str, max_chars: int, start_line: int, end_line: int,
                    symbol_name: Optional[str]) -> List[Dict[str, Any]]:
    """单行超长（压缩代码）时的兜底：按字符硬切，行号沿用所在区间。"""
    return [
        {
            "content": text[index:index + max_chars],
            "symbolName": symbol_name,
            "startLine": start_line,
            "endLine": end_line,
        }
        for index in range(0, len(text), max_chars)
    ]


def build_chunks(
    content: str,
    structure: Optional[Dict[str, Any]],
    *,
    max_lines: int,
    overlap: int,
    max_chars: int,
) -> List[Dict[str, Any]]:
    """把一份文件内容切成 Chunk 列表，每项含 content / symbolName / startLine / endLine。"""
    if not content or not content.strip():
        return []

    lines = content.split("\n")
    total_lines = len(lines)
    segments = build_segments(structure or {}, total_lines)

    chunks: List[Dict[str, Any]] = []
    for start, end, symbol_name in segments:
        segment_text = "\n".join(lines[start - 1:end])
        if not segment_text.strip():
            continue
        if end - start + 1 <= max_lines and len(segment_text) <= max_chars:
            chunks.append({
                "content": segment_text,
                "symbolName": symbol_name,
                "startLine": start,
                "endLine": end,
            })
            continue

        for text, relative_start in rag_service.chunk_content_with_offsets(segment_text, max_lines, overlap):
            absolute_start = start + relative_start - 1
            absolute_end = min(absolute_start + text.count("\n"), end)
            if len(text) <= max_chars:
                chunks.append({
                    "content": text,
                    "symbolName": symbol_name,
                    "startLine": absolute_start,
                    "endLine": absolute_end,
                })
            else:
                chunks.extend(
                    _split_by_chars(text, max_chars, absolute_start, absolute_end, symbol_name)
                )
    return chunks
