"""Semantic cache for AI generations.

Hits are matched by embedding similarity of the request signature, so
slightly modified code or repeated requests reuse a previous result and
skip the model call (saving tokens and cost).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np

from database import get_conn
from services.embedding_service import embed_query

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.98


def build_signature(code: str, language: str, style: str, task: str, kb_version: str = "") -> str:
    normalized = " ".join(code.split())
    return f"lang={language}|style={style}|task={task}|kb={kb_version}|code={normalized}"


def _kb_version(user_id: int) -> str:
    conn = get_conn()
    docs = conn.execute("SELECT COUNT(*) AS c FROM rag_documents WHERE user_id=?", (user_id,)).fetchone()["c"]
    chunks = conn.execute("SELECT COUNT(*) AS c FROM rag_chunks WHERE user_id=?", (user_id,)).fetchone()["c"]
    conn.close()
    return f"{docs}:{chunks}"


def lookup(user_id: int, signature: str, kb_version: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, signature, embedding_json, result_json FROM ai_cache WHERE user_id=?",
        (user_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return None

    matrix = np.asarray([json.loads(r["embedding_json"]) for r in rows], dtype=np.float32)
    query = embed_query(signature)
    if matrix.shape[1] != query.shape[0]:
        # Embedding 模式/维度变化后旧缓存已不可比较，直接作废重建，避免维度错误中断生成
        logger.warning("语义缓存向量维度不一致（%s vs %s），清空该用户旧缓存", matrix.shape[1], query.shape[0])
        clear(user_id)
        return None

    # 版本必须精确匹配：版本号只是签名的一小段，代码越长它对余弦的影响越小，
    # 只靠相似度阈值无法保证"知识库一变就 miss"（长代码下版本变化仅约 0.001）。
    marker = f"|kb={kb_version}|code="
    selected = [i for i, row in enumerate(rows) if marker in (row["signature"] or "")]
    if not selected:
        return None

    scores = matrix[selected] @ query
    best = int(np.argmax(scores))
    best_score = float(scores[best])
    if best_score < SIMILARITY_THRESHOLD:
        return None

    best_row = rows[selected[best]]
    conn = get_conn()
    conn.execute("UPDATE ai_cache SET hits = hits + 1 WHERE id=?", (best_row["id"],))
    conn.commit()
    conn.close()
    return {"score": round(best_score, 4), "result": json.loads(best_row["result_json"])}


def store(user_id: int, signature: str, result: Dict[str, Any]) -> None:
    embedding = embed_query(signature)
    conn = get_conn()
    existing = conn.execute(
        "SELECT embedding_json FROM ai_cache WHERE user_id=? LIMIT 1",
        (user_id,),
    ).fetchone()
    if existing and len(json.loads(existing["embedding_json"])) != embedding.shape[0]:
        conn.execute("DELETE FROM ai_cache WHERE user_id=?", (user_id,))
    conn.execute(
        "INSERT INTO ai_cache(user_id,signature,embedding_json,result_json,hits,created_at) VALUES(?,?,?,?,0,?)",
        (user_id, signature, json.dumps(embedding.tolist()), json.dumps(result, ensure_ascii=False),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def clear(user_id: int) -> int:
    conn = get_conn()
    cur = conn.execute("DELETE FROM ai_cache WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    return cur.rowcount


def stats(user_id: int) -> Dict[str, Any]:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS entries, COALESCE(SUM(hits),0) AS hits FROM ai_cache WHERE user_id=?",
        (user_id,),
    ).fetchone()
    conn.close()
    return {"entries": row["entries"], "hits": row["hits"]}
