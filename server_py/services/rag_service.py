"""RAG (retrieval-augmented generation) service: chunking, indexing, hybrid search."""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from database import get_conn
from services.embedding_service import embed_query, embed_texts, embedding_mode

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_LINES = 40
DEFAULT_OVERLAP_LINES = 10

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]")
VECTOR_WEIGHT = 0.65
BM25_WEIGHT = 0.35
RERANK_POOL_FACTOR = 4
# 单次向量化的最大条数：批次过大会撑爆远程 Embedding 接口的请求体，
# 也会让本地哈希向量一次性占用过多内存
EMBED_BATCH_SIZE = 64
# 中文按单字切词时，这些高频虚词几乎出现在任何一段中文文本里。不把它们摘掉的话，
# 词面覆盖率会被抬到接近 1：既让"证据门槛"形同虚设，也会在重排时把实现代码挤到文档后面。
_CJK_STOP_CHARS = frozenset(
    "的了在是我你他她它这那们和与或有不就都而及其为以于之上中里吗呢吧啊呀哦"
    "个之也还就都很把被从对能给让使所则若且但并等什怎谓该此这些那些哪个什么怎么"
)
# 来源先验：项目级问答默认问的是"实现在哪"，所以实现代码权重最高；
# 文档常含架构说明，仍有价值但略降；测试文件虽然同样会命中关键词，
# 但极少是"实现位置"的权威来源，降权最多（测量见 2026-10 的检索对比）。
SOURCE_KIND_WEIGHTS = {"code": 1.15, "doc": 0.95, "test": 0.5}


def _content_tokens(text: str) -> set:
    """用于词面覆盖率的内容词集合（已去掉中文单字虚词）。"""
    return {token for token in _tokenize(text) if token not in _CJK_STOP_CHARS}


def source_kind(rel_path: Optional[str], language: Optional[str]) -> str:
    """按来源给 Chunk 分类，供检索时的先验加权使用。"""
    if (language or "") == "text":
        return "doc"
    path = (rel_path or "").lower()
    if not path:
        return "code"
    name = path.rsplit("/", 1)[-1]
    if "/tests/" in path or path.startswith("tests/") or name.startswith("test_") or name.endswith("_test.py"):
        return "test"
    return "code"


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def _bm25_scores(query_tokens: List[str], doc_tokens: List[List[str]], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    n = len(doc_tokens)
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    avgdl = sum(len(d) for d in doc_tokens) / n or 1.0
    df: Counter = Counter()
    for doc in doc_tokens:
        for token in set(doc):
            df[token] += 1

    scores = np.zeros(n, dtype=np.float32)
    for i, doc in enumerate(doc_tokens):
        counts = Counter(doc)
        dl = len(doc) or 1
        total = 0.0
        for token in query_tokens:
            tf = counts.get(token)
            if not tf:
                continue
            idf = math.log(1 + (n - df[token] + 0.5) / (df[token] + 0.5))
            total += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
        scores[i] = total
    return scores


def _normalize(scores: np.ndarray) -> np.ndarray:
    if scores.size == 0:
        return scores
    top = float(scores.max())
    if top <= 0:
        return np.zeros_like(scores)
    return scores / top


def _lexical_overlap(query_tokens: set, doc_tokens: set) -> float:
    if not query_tokens:
        return 0.0
    return len(query_tokens & doc_tokens) / len(query_tokens)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def chunk_content_with_offsets(
    content: str,
    max_lines: int = DEFAULT_CHUNK_LINES,
    overlap: int = DEFAULT_OVERLAP_LINES,
) -> List[tuple]:
    """按行窗口切分，返回 ``[(chunk_text, start_line)]``（start_line 为 1 基行号）。

    切分行为与历史实现完全一致；多返回起始行号是为了让每个 Chunk 都能标注
    自己在源文件中的位置（项目级知识库需要"来源文件 + 行号"的引用信息）。
    """
    lines = content.split("\n")
    if len(lines) <= max_lines:
        stripped = content.strip()
        return [(stripped, 1)] if stripped else []

    chunks: List[tuple] = []
    step = max(1, max_lines - overlap)
    for start in range(0, len(lines), step):
        block = "\n".join(lines[start:start + max_lines]).strip()
        if block:
            chunks.append((block, start + 1))
        if start + max_lines >= len(lines):
            break
    return chunks


def chunk_content(content: str, max_lines: int = DEFAULT_CHUNK_LINES, overlap: int = DEFAULT_OVERLAP_LINES) -> List[str]:
    return [text for text, _ in chunk_content_with_offsets(content, max_lines, overlap)]


def _embed_in_batches(texts: List[str]) -> np.ndarray:
    """分批向量化，避免一次性把整份文档/整个项目的 Chunk 丢给 Embedding 接口。"""
    if len(texts) <= EMBED_BATCH_SIZE:
        return embed_texts(texts)
    parts = [
        embed_texts(texts[index:index + EMBED_BATCH_SIZE])
        for index in range(0, len(texts), EMBED_BATCH_SIZE)
    ]
    return np.vstack(parts)


def _dimension_scope_sql(project_id: Optional[int]) -> tuple:
    """维度校验的查询范围：手动知识库与每个项目各自独立。"""
    if project_id is None:
        return " AND project_id IS NULL", []
    return " AND project_id=?", [project_id]


def check_embedding_dimension(user_id: int, dim: int, project_id: Optional[int] = None) -> None:
    """校验同一作用域内已有向量与当前 Embedding 维度是否一致，不一致则抛 ValueError。"""
    scope_sql, scope_params = _dimension_scope_sql(project_id)
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT embedding_json FROM rag_chunks WHERE user_id=?" + scope_sql + " LIMIT 1",
            tuple([user_id] + scope_params),
        ).fetchone()
    finally:
        conn.close()
    if not existing:
        return
    existing_dim = len(json.loads(existing["embedding_json"]))
    if existing_dim != dim:
        raise ValueError(
            f"Embedding 维度（{dim} 维）与已有知识库（{existing_dim} 维）不一致，"
            "通常由切换本地/远程 Embedding 引起，请删除旧知识库文档后重新索引"
        )


def add_document(
    user_id: int,
    title: str,
    content: str,
    language: str = "text",
    source: str = "manual",
    project_id: Optional[int] = None,
    rel_path: Optional[str] = None,
) -> Dict[str, Any]:
    """写入手动知识库文档。

    ``project_id`` 默认 ``None`` 表示手动/团队规范库，行为与历史版本一致；
    传入项目 ID 时归入该项目知识库（项目文件走 ``index_project_file`` 以获得符号级元数据）。
    """
    chunk_pairs = chunk_content_with_offsets(content)
    if not chunk_pairs:
        raise ValueError("文档内容为空")

    embeddings = _embed_in_batches([text for text, _ in chunk_pairs])
    dim = int(embeddings.shape[1])
    check_embedding_dimension(user_id, dim, project_id)
    created = _now()

    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO rag_documents(user_id,title,source,language,char_count,chunk_count,project_id,rel_path,line_count,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                user_id, title, source, language, len(content), len(chunk_pairs),
                project_id, rel_path, content.count("\n") + 1, created,
            ),
        )
        document_id = cur.lastrowid
        for index, ((chunk, start_line), vector) in enumerate(zip(chunk_pairs, embeddings, strict=True)):
            conn.execute(
                "INSERT INTO rag_chunks(document_id,user_id,chunk_index,content,embedding_json,project_id,rel_path,language,start_line,end_line,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    document_id, user_id, index, chunk, json.dumps(vector.tolist()),
                    project_id, rel_path, language, start_line,
                    start_line + chunk.count("\n"), created,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "id": document_id,
        "title": title,
        "language": language,
        "source": source,
        "chunkCount": len(chunk_pairs),
        "charCount": len(content),
        "createdAt": created,
    }


def index_project_file(
    user_id: int,
    project_id: int,
    rel_path: str,
    language: str,
    content: str,
    structure: Optional[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    expected_dim: Optional[int] = None,
) -> int:
    """把一个项目文件的符号级 Chunk（含结构信息）写入知识库，返回写入的 Chunk 数。

    一个文件对应一条 ``rag_documents``（``title``/``rel_path`` 都是相对路径），
    其 Chunk 落在 ``rag_chunks`` 中并带上 project_id / rel_path / symbol_name / 行号区间。
    维度一致性由项目级 ``check_embedding_dimension`` 统一负责，这里不再逐文件重复校验。

    ``expected_dim`` 传入时逐个文件复核维度：Embedding API 中途失败会静默降级为本地
    哈希向量（维度不同），如果不在写入前拦住，同一个项目里就会混入两种维度的向量，
    导致后续检索整体失败。
    """
    if not chunks:
        return 0

    texts = [str(item["content"]) for item in chunks]
    embeddings = _embed_in_batches(texts)
    if expected_dim is not None and int(embeddings.shape[1]) != expected_dim:
        raise ValueError(
            f"文件 {rel_path} 的向量维度（{int(embeddings.shape[1])}）与项目索引维度（{expected_dim}）不一致，"
            "通常由 Embedding 接口中途不可用触发本地降级引起，请稍后重新上传"
        )
    created = _now()

    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO rag_documents(user_id,title,source,language,char_count,chunk_count,project_id,rel_path,line_count,structure_json,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                user_id, rel_path, "project", language, len(content), len(chunks),
                project_id, rel_path, content.count("\n") + 1,
                json.dumps(structure, ensure_ascii=False) if structure else None,
                created,
            ),
        )
        document_id = cur.lastrowid
        for index, (item, vector) in enumerate(zip(chunks, embeddings, strict=True)):
            symbol_name = item.get("symbolName")
            conn.execute(
                "INSERT INTO rag_chunks(document_id,user_id,chunk_index,content,embedding_json,project_id,rel_path,language,symbol_name,start_line,end_line,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    document_id, user_id, index, texts[index], json.dumps(vector.tolist()),
                    project_id, rel_path, language,
                    str(symbol_name) if symbol_name else None,
                    int(item.get("startLine") or 0), int(item.get("endLine") or 0),
                    created,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return len(chunks)


def list_project_files(user_id: int, project_id: int) -> List[Dict[str, Any]]:
    """项目文件清单（每个文件一条 rag_documents）。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, rel_path, title, language, char_count, chunk_count, line_count, structure_json, created_at"
            " FROM rag_documents WHERE user_id=? AND project_id=? ORDER BY rel_path",
            (user_id, project_id),
        ).fetchall()
    finally:
        conn.close()

    files = []
    for row in rows:
        structure = None
        if row["structure_json"]:
            try:
                structure = json.loads(row["structure_json"])
            except (TypeError, ValueError):
                structure = None
        symbol_count = 0
        if isinstance(structure, dict):
            symbol_count = len(structure.get("functions") or []) + len(structure.get("classes") or [])
        files.append({
            "id": row["id"],
            "relPath": row["rel_path"] or row["title"],
            "language": row["language"],
            "charCount": row["char_count"],
            "chunkCount": row["chunk_count"],
            "lineCount": row["line_count"],
            "symbolCount": symbol_count,
            "createdAt": row["created_at"],
        })
    return files


def get_project_file(user_id: int, project_id: int, document_id: int) -> Optional[Dict[str, Any]]:
    """单个项目文件的结构与分块详情。"""
    conn = get_conn()
    try:
        document = conn.execute(
            "SELECT id, rel_path, language, char_count, chunk_count, line_count, structure_json, created_at"
            " FROM rag_documents WHERE id=? AND user_id=? AND project_id=?",
            (document_id, user_id, project_id),
        ).fetchone()
        if not document:
            return None
        chunks = conn.execute(
            "SELECT chunk_index, symbol_name, start_line, end_line, content"
            " FROM rag_chunks WHERE document_id=? ORDER BY chunk_index",
            (document_id,),
        ).fetchall()
    finally:
        conn.close()

    structure = None
    if document["structure_json"]:
        try:
            structure = json.loads(document["structure_json"])
        except (TypeError, ValueError):
            structure = None
    return {
        "id": document["id"],
        "relPath": document["rel_path"],
        "language": document["language"],
        "charCount": document["char_count"],
        "chunkCount": document["chunk_count"],
        "lineCount": document["line_count"],
        "structure": structure,
        "createdAt": document["created_at"],
        "chunks": [
            {
                "index": row["chunk_index"],
                "symbolName": row["symbol_name"],
                "startLine": row["start_line"],
                "endLine": row["end_line"],
                "content": row["content"],
            }
            for row in chunks
        ],
    }


def delete_project_documents(user_id: int, project_id: int) -> int:
    """删除某个项目的全部文档与 Chunk，返回删除的文档数。"""
    conn = get_conn()
    try:
        documents = conn.execute(
            "SELECT COUNT(*) AS c FROM rag_documents WHERE user_id=? AND project_id=?",
            (user_id, project_id),
        ).fetchone()["c"]
        conn.execute("DELETE FROM rag_chunks WHERE user_id=? AND project_id=?", (user_id, project_id))
        conn.execute("DELETE FROM rag_documents WHERE user_id=? AND project_id=?", (user_id, project_id))
        conn.commit()
    finally:
        conn.close()
    return documents


def delete_all_user_project_documents(user_id: int) -> None:
    """删除该用户所有项目文档与 Chunk（注销/删号级联用）。"""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM rag_chunks WHERE user_id=? AND project_id IS NOT NULL", (user_id,))
        conn.execute("DELETE FROM rag_documents WHERE user_id=? AND project_id IS NOT NULL", (user_id,))
        conn.commit()
    finally:
        conn.close()


def list_documents(user_id: int) -> List[Dict[str, Any]]:
    """手动/团队规范库的文档列表（不含项目文件，项目文件在项目页查看）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id,title,source,language,char_count,chunk_count,created_at"
        " FROM rag_documents WHERE user_id=? AND project_id IS NULL ORDER BY id DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "source": r["source"],
            "language": r["language"],
            "charCount": r["char_count"],
            "chunkCount": r["chunk_count"],
            "createdAt": r["created_at"],
        }
        for r in rows
    ]


def get_document(user_id: int, document_id: int) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    doc = conn.execute(
        "SELECT id,title,source,language,char_count,chunk_count,created_at FROM rag_documents WHERE id=? AND user_id=?",
        (document_id, user_id),
    ).fetchone()
    if not doc:
        conn.close()
        return None
    chunks = conn.execute(
        "SELECT chunk_index,content FROM rag_chunks WHERE document_id=? ORDER BY chunk_index",
        (document_id,),
    ).fetchall()
    conn.close()
    return {
        "id": doc["id"],
        "title": doc["title"],
        "source": doc["source"],
        "language": doc["language"],
        "charCount": doc["char_count"],
        "chunkCount": doc["chunk_count"],
        "createdAt": doc["created_at"],
        "chunks": [{"index": c["chunk_index"], "content": c["content"]} for c in chunks],
    }


def delete_document(user_id: int, document_id: int) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT id FROM rag_documents WHERE id=? AND user_id=?", (document_id, user_id)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("DELETE FROM rag_chunks WHERE document_id=? AND user_id=?", (document_id, user_id))
    conn.execute("DELETE FROM rag_documents WHERE id=? AND user_id=?", (document_id, user_id))
    conn.commit()
    conn.close()
    return True


def search(
    user_id: int,
    query: str,
    top_k: int = 4,
    project_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """混合检索：向量余弦 + BM25 加权，再做词面重排。

    ``project_id=None`` 只检索手动/团队规范库（``project_id IS NULL``），
    传入项目 ID 则只检索该项目——项目之间的向量互不可见，这是项目隔离的执行点。
    """
    conn = get_conn()
    try:
        sql = (
            "SELECT c.id, c.document_id, c.chunk_index, c.content, c.embedding_json,"
            " c.rel_path, c.symbol_name, c.start_line, c.end_line, d.title, d.language"
            " FROM rag_chunks c JOIN rag_documents d ON c.document_id = d.id"
            " WHERE c.user_id=?"
        )
        params: List[Any] = [user_id]
        if project_id is None:
            sql += " AND c.project_id IS NULL"
        else:
            sql += " AND c.project_id=?"
            params.append(project_id)
        rows = conn.execute(sql, tuple(params)).fetchall()
    finally:
        # 历史实现在维度不一致分支里对已关闭的连接二次 close，
        # 在 DBUtils 连接池下会把同一个连接重复归还，这里统一用 try/finally 收口
        conn.close()

    if not rows:
        return []

    contents = [r["content"] for r in rows]
    query_tokens = _tokenize(query)
    # 词面覆盖率用"内容词"计算（去掉中文单字虚词），否则一句中文问题会和任何中文文本
    # 都产生高覆盖率，把文档顶到实现代码前面
    query_set = _content_tokens(query)
    doc_token_lists = [_tokenize(c) for c in contents]

    matrix = np.asarray([json.loads(r["embedding_json"]) for r in rows], dtype=np.float32)
    query_vec = embed_query(query)
    if matrix.shape[1] != query_vec.shape[0]:
        raise RuntimeError(
            f"知识库向量维度 {matrix.shape[1]} 与当前 Embedding 维度 {query_vec.shape[0]} 不一致，"
            "请删除旧知识库文档后重新索引"
        )
    vector_scores = matrix @ query_vec

    bm25_scores = _bm25_scores(query_tokens, doc_token_lists)

    combined = VECTOR_WEIGHT * _normalize(vector_scores) + BM25_WEIGHT * _normalize(bm25_scores)

    pool_size = min(len(rows), max(top_k * RERANK_POOL_FACTOR, 20))
    pool = np.argsort(-combined)[:pool_size]

    reranked = []
    for index in pool:
        overlap = _lexical_overlap(query_set, _content_tokens(contents[index]))
        # 先按综合分与词面覆盖率重排，再乘来源先验：实现代码优先于文档，测试文件最后
        kind = source_kind(rows[index]["rel_path"], rows[index]["language"])
        rerank_score = (0.5 * float(combined[index]) + 0.5 * overlap) * SOURCE_KIND_WEIGHTS[kind]
        reranked.append((int(index), float(combined[index]), overlap, rerank_score))
    reranked.sort(key=lambda item: item[3], reverse=True)

    results = []
    for index, combined_score, overlap, rerank_score in reranked[:top_k]:
        row = rows[index]
        kind = source_kind(row["rel_path"], row["language"])
        results.append({
            "documentId": row["document_id"],
            "title": row["title"],
            "language": row["language"],
            "sourceKind": kind,
            "chunkIndex": row["chunk_index"],
            "score": round(combined_score, 4),
            "rerankScore": round(rerank_score, 4),
            "lexicalOverlap": round(overlap, 4),
            # 项目文件的来源信息（手动知识库为 None/0），用于生成"来源文件 + 行号"引用
            "relPath": row["rel_path"],
            "symbolName": row["symbol_name"],
            "startLine": row["start_line"] or 0,
            "endLine": row["end_line"] or 0,
            "content": row["content"],
        })
    return results


def build_context(
    user_id: int,
    query: str,
    top_k: int = 4,
    min_score: float = 0.05,
    project_id: Optional[int] = None,
    max_chars: int = 0,
    require_overlap: bool = False,
):
    """返回注入 Prompt 的 ``(context_text, metadata)``。

    ``max_chars`` 大于 0 时对注入文本做长度预算截断，避免把整个项目一次性塞进 Prompt；
    默认 0 表示不限制，保持单文件生成链路的历史行为。

    ``require_overlap`` 为 True 时，只保留与问题存在词面交叠的片段：问答场景用它
    挡住"问题与项目内容完全无关"的情况，避免把无关代码喂给模型后让它凭空编造。
    """
    try:
        hits = search(user_id, query, top_k, project_id=project_id)
    except Exception:
        # 生成主流程不能被 RAG 故障打断，但必须留下可排查的日志，
        # 避免知识库静默失效（如 Embedding 维度不一致）。
        logger.exception("RAG 检索失败，本次生成不注入知识库上下文")
        return "", []
    hits = [h for h in hits if h["score"] >= min_score]
    if require_overlap:
        hits = [h for h in hits if h.get("lexicalOverlap", 0) > 0]
    if not hits:
        return "", []

    parts: List[str] = []
    used_chars = 0
    accepted: List[Dict[str, Any]] = []
    for i, hit in enumerate(hits, 1):
        source = hit.get("relPath") or hit["title"]
        location = (
            f" L{hit['startLine']}-{hit['endLine']}"
            if hit.get("startLine") and hit.get("endLine")
            else f" 第{hit['chunkIndex'] + 1}块"
        )
        symbol = f" {hit['symbolName']}" if hit.get("symbolName") else ""
        part = (
            f"[片段{len(accepted) + 1}] 来源《{source}》{location}{symbol}"
            f" (相似度 {hit['score']})\n{hit['content']}"
        )
        # 至少保留第一个片段：即便单块就超过预算，也不让检索结果整体落空
        if max_chars and accepted and used_chars + len(part) > max_chars:
            logger.info("RAG 上下文已达长度预算 %s，截断剩余 %s 个片段", max_chars, len(hits) - len(accepted))
            break
        parts.append(part)
        accepted.append(hit)
        used_chars += len(part)
    if not parts:
        return "", []

    context_text = "\n\n".join(parts)
    metadata = [
        {
            "documentId": h["documentId"],
            "title": h["title"],
            "relPath": h.get("relPath"),
            "symbolName": h.get("symbolName"),
            "startLine": h.get("startLine"),
            "endLine": h.get("endLine"),
            "chunkIndex": h["chunkIndex"],
            "score": h["score"],
            "lexicalOverlap": h.get("lexicalOverlap"),
            "rerankScore": h.get("rerankScore"),
            "preview": h["content"][:160],
        }
        for h in accepted
    ]
    return context_text, metadata


def get_stats(user_id: int) -> Dict[str, Any]:
    """手动/团队规范库统计（不含项目文件）。"""
    conn = get_conn()
    docs = conn.execute(
        "SELECT COUNT(*) AS c FROM rag_documents WHERE user_id=? AND project_id IS NULL", (user_id,)
    ).fetchone()["c"]
    chunks = conn.execute(
        "SELECT COUNT(*) AS c FROM rag_chunks WHERE user_id=? AND project_id IS NULL", (user_id,)
    ).fetchone()["c"]
    conn.close()
    return {"documents": docs, "chunks": chunks, "embeddingMode": embedding_mode()}
