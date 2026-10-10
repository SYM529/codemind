import json

import pytest

from database import get_conn
from services import rag_service

DIM_MISMATCH_USER = 9091


def _seed_fake_dimension_chunk(dim: int = 32):
    conn = get_conn()
    conn.execute(
        "INSERT INTO rag_documents(user_id,title,source,language,char_count,chunk_count,created_at) VALUES(?,?,?,?,?,?,?)",
        (DIM_MISMATCH_USER, "old-doc", "manual", "text", 4, 1, "2026-01-01T00:00:00+00:00"),
    )
    doc_id = conn.execute(
        "SELECT id FROM rag_documents WHERE user_id=?", (DIM_MISMATCH_USER,)
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO rag_chunks(document_id,user_id,chunk_index,content,embedding_json,created_at) VALUES(?,?,?,?,?,?)",
        (doc_id, DIM_MISMATCH_USER, 0, "legacy chunk", json.dumps([0.1] * dim), "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()


def _cleanup_dim_mismatch_user():
    conn = get_conn()
    conn.execute("DELETE FROM rag_chunks WHERE user_id=?", (DIM_MISMATCH_USER,))
    conn.execute("DELETE FROM rag_documents WHERE user_id=?", (DIM_MISMATCH_USER,))
    conn.commit()
    conn.close()


def test_chunk_content_splits_and_overlaps():
    content = "\n".join(f"line {i}" for i in range(100))
    chunks = rag_service.chunk_content(content, max_lines=40, overlap=10)
    assert len(chunks) >= 3
    assert "line 0" in chunks[0]
    assert "line 39" in chunks[0]
    # overlap: second chunk starts at line 30
    assert "line 30" in chunks[1]


def test_chunk_content_short_returns_single():
    assert rag_service.chunk_content("only one line") == ["only one line"]


def test_add_document_and_hybrid_search():
    user_id = 4242
    doc = rag_service.add_document(
        user_id,
        "auth.js",
        "export async function login(username, password) { const user = await db.findUser(username); "
        "if (!user) throw new Error('INVALID_CREDENTIALS'); return signJwt(user); }",
        language="javascript",
    )
    assert doc["chunkCount"] >= 1

    results = rag_service.search(user_id, "login username password signJwt", top_k=3)
    assert results
    assert results[0]["title"] == "auth.js"
    assert "rerankScore" in results[0]

    context, meta = rag_service.build_context(user_id, "login username password signJwt", top_k=3)
    assert "auth.js" in context
    assert meta[0]["title"] == "auth.js"

    assert rag_service.delete_document(user_id, doc["id"]) is True
    assert rag_service.search(user_id, "login", top_k=3) == []


def test_embedding_dimension_mismatch_is_rejected():
    # 模拟切换 Embedding 模式后遗留的旧维度索引（32 维 vs 本地 512 维）
    _seed_fake_dimension_chunk()
    try:
        with pytest.raises(ValueError):
            rag_service.add_document(
                DIM_MISMATCH_USER, "new-doc", "function login(password) { verify(password); }", "javascript"
            )
        with pytest.raises(RuntimeError):
            rag_service.search(DIM_MISMATCH_USER, "login password", top_k=2)
        # 生成主流程注入上下文时不得抛异常，返回空上下文由调用方降级
        context, meta = rag_service.build_context(DIM_MISMATCH_USER, "login password", top_k=2)
        assert context == ""
        assert meta == []
    finally:
        _cleanup_dim_mismatch_user()
