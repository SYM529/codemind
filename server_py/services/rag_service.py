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


def chunk_content(content: str, max_lines: int = DEFAULT_CHUNK_LINES, overlap: int = DEFAULT_OVERLAP_LINES) -> List[str]:
    lines = content.split("\n")
    if len(lines) <= max_lines:
        stripped = content.strip()
        return [stripped] if stripped else []

    chunks: List[str] = []
    step = max(1, max_lines - overlap)
    for start in range(0, len(lines), step):
        block = "\n".join(lines[start:start + max_lines]).strip()
        if block:
            chunks.append(block)
        if start + max_lines >= len(lines):
            break
    return chunks


def add_document(user_id: int, title: str, content: str, language: str = "text", source: str = "manual") -> Dict[str, Any]:
    chunks = chunk_content(content)
    if not chunks:
        raise ValueError("文档内容为空")

    embeddings = embed_texts(chunks)
    dim = int(embeddings.shape[1])
    created = _now()

    conn = get_conn()
    existing = conn.execute(
        "SELECT embedding_json FROM rag_chunks WHERE user_id=? LIMIT 1",
        (user_id,),
    ).fetchone()
    if existing:
        existing_dim = len(json.loads(existing["embedding_json"]))
        if existing_dim != dim:
            conn.close()
            raise ValueError(
                f"Embedding 维度（{dim} 维）与已有知识库（{existing_dim} 维）不一致，"
                "通常由切换本地/远程 Embedding 引起，请删除旧知识库文档后重新索引"
            )
    cur = conn.execute(
        "INSERT INTO rag_documents(user_id,title,source,language,char_count,chunk_count,created_at) VALUES(?,?,?,?,?,?,?)",
        (user_id, title, source, language, len(content), len(chunks), created),
    )
    document_id = cur.lastrowid
    for index, (chunk, vector) in enumerate(zip(chunks, embeddings, strict=True)):
        conn.execute(
            "INSERT INTO rag_chunks(document_id,user_id,chunk_index,content,embedding_json,created_at) VALUES(?,?,?,?,?,?)",
            (document_id, user_id, index, chunk, json.dumps(vector.tolist()), created),
        )
    conn.commit()
    conn.close()

    return {
        "id": document_id,
        "title": title,
        "language": language,
        "source": source,
        "chunkCount": len(chunks),
        "charCount": len(content),
        "createdAt": created,
    }


def list_documents(user_id: int) -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id,title,source,language,char_count,chunk_count,created_at"
        " FROM rag_documents WHERE user_id=? ORDER BY id DESC",
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


def search(user_id: int, query: str, top_k: int = 4) -> List[Dict[str, Any]]:
    """Hybrid retrieval: vector cosine + BM25, then lexical rerank."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT c.id, c.document_id, c.chunk_index, c.content, c.embedding_json, d.title, d.language"
        " FROM rag_chunks c JOIN rag_documents d ON c.document_id = d.id"
        " WHERE c.user_id=?",
        (user_id,),
    ).fetchall()
    conn.close()

    if not rows:
        return []

    contents = [r["content"] for r in rows]
    query_tokens = _tokenize(query)
    query_set = set(query_tokens)
    doc_token_lists = [_tokenize(c) for c in contents]

    matrix = np.asarray([json.loads(r["embedding_json"]) for r in rows], dtype=np.float32)
    query_vec = embed_query(query)
    if matrix.shape[1] != query_vec.shape[0]:
        conn.close()
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
        overlap = _lexical_overlap(query_set, set(doc_token_lists[index]))
        rerank_score = 0.5 * float(combined[index]) + 0.5 * overlap
        reranked.append((int(index), float(combined[index]), overlap, rerank_score))
    reranked.sort(key=lambda item: item[3], reverse=True)

    results = []
    for index, combined_score, overlap, rerank_score in reranked[:top_k]:
        row = rows[index]
        results.append({
            "documentId": row["document_id"],
            "title": row["title"],
            "language": row["language"],
            "chunkIndex": row["chunk_index"],
            "score": round(combined_score, 4),
            "rerankScore": round(rerank_score, 4),
            "lexicalOverlap": round(overlap, 4),
            "content": row["content"],
        })
    return results


def build_context(user_id: int, query: str, top_k: int = 4, min_score: float = 0.05):
    """Return (context_text, retrieved_metadata) for prompt injection."""
    try:
        hits = search(user_id, query, top_k)
    except Exception:
        # 生成主流程不能被 RAG 故障打断，但必须留下可排查的日志，
        # 避免知识库静默失效（如 Embedding 维度不一致）。
        logger.exception("RAG 检索失败，本次生成不注入知识库上下文")
        return "", []
    hits = [h for h in hits if h["score"] >= min_score]
    if not hits:
        return "", []

    parts = []
    for i, hit in enumerate(hits, 1):
        parts.append(f"[片段{i}] 来源《{hit['title']}》第{hit['chunkIndex'] + 1}块 (相似度 {hit['score']})\n{hit['content']}")
    context_text = "\n\n".join(parts)
    metadata = [
        {
            "documentId": h["documentId"],
            "title": h["title"],
            "chunkIndex": h["chunkIndex"],
            "score": h["score"],
            "preview": h["content"][:160],
        }
        for h in hits
    ]
    return context_text, metadata


def get_stats(user_id: int) -> Dict[str, Any]:
    conn = get_conn()
    docs = conn.execute("SELECT COUNT(*) AS c FROM rag_documents WHERE user_id=?", (user_id,)).fetchone()["c"]
    chunks = conn.execute("SELECT COUNT(*) AS c FROM rag_chunks WHERE user_id=?", (user_id,)).fetchone()["c"]
    conn.close()
    return {"documents": docs, "chunks": chunks, "embeddingMode": embedding_mode()}
