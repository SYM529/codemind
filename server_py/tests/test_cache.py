import json

from database import get_conn
from services import cache_service


def test_signature_normalizes_whitespace():
    a = cache_service.build_signature("function  a() {\n  return 1;\n}", "javascript", "default", "comment", "1:1")
    b = cache_service.build_signature("function a() { return 1; }", "javascript", "default", "comment", "1:1")
    assert a == b


def test_signature_changes_with_kb_version():
    a = cache_service.build_signature("x", "javascript", "default", "comment", "1:1")
    b = cache_service.build_signature("x", "javascript", "default", "comment", "1:2")
    assert a != b


def test_store_and_lookup_hit():
    user_id = 5150
    signature = cache_service.build_signature("function x(){}", "javascript", "default", "comment", "0:0")
    result = {"summary": "cached", "comments": [], "risks": [], "suggestions": [], "debug": {}}
    cache_service.store(user_id, signature, result)

    hit = cache_service.lookup(user_id, signature)
    assert hit is not None
    assert hit["result"]["summary"] == "cached"

    stats = cache_service.stats(user_id)
    assert stats["entries"] >= 1
    assert stats["hits"] >= 1

    cache_service.clear(user_id)
    assert cache_service.lookup(user_id, signature) is None


def test_lookup_dimension_mismatch_auto_clears():
    # 旧维度（32 维）缓存与当前本地向量（512 维）不可比较时，应自动作废而非报错
    user_id = 6262
    conn = get_conn()
    conn.execute(
        "INSERT INTO ai_cache(user_id,signature,embedding_json,result_json,hits,created_at) VALUES(?,?,?,?,0,?)",
        (user_id, "legacy", json.dumps([0.1] * 32), json.dumps({"summary": "x"}), "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    signature = cache_service.build_signature("function y(){}", "javascript", "default", "comment", "0:0")
    assert cache_service.lookup(user_id, signature) is None
    assert cache_service.stats(user_id)["entries"] == 0
