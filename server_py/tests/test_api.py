"""路由层集成测试：鉴权、RBAC、用户数据隔离、未配置 AI 时的降级、注销级联删除。"""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _register(username, email, password="Test123456"):
    return client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password},
    )


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _ensure_token(username, email, password):
    """管理员可能已被其他测试模块的引导机制创建，此时直接复用已有账号。"""
    resp = _register(username, email, password)
    if resp.status_code == 409:
        resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


@pytest.fixture(scope="module")
def users():
    return {
        "admin_token": _ensure_token("admin", "admin@example.com", "Admin123456"),
        "alice_token": _register("alice", "alice@example.com", "Alice123456").json()["token"],
        "bob_token": _register("bob", "bob@example.com", "Bob123456").json()["token"],
    }


def test_health_ok():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"]


def test_protected_endpoints_require_login():
    assert client.get("/api/ai/history").status_code == 401
    assert client.get("/api/rag/documents").status_code == 401
    assert client.get("/api/admin/metrics").status_code == 401
    # 伪造 token 同样被拒
    assert client.get("/api/ai/history", headers=_auth("not-a-real-token")).status_code == 401


def test_admin_bootstrap_and_rbac(users):
    me = client.get("/api/auth/me", headers=_auth(users["admin_token"])).json()
    assert me["user"]["role"] == "admin"

    resp_admin = client.get("/api/admin/metrics", headers=_auth(users["admin_token"]))
    assert resp_admin.status_code == 200
    assert resp_admin.json()["metrics"]["users"] >= 3

    resp_forbidden = client.get("/api/admin/metrics", headers=_auth(users["alice_token"]))
    assert resp_forbidden.status_code == 403


def test_rag_documents_are_isolated_per_user(users):
    payload = {
        "title": "alice-auth-spec",
        "language": "javascript",
        "content": (
            "export async function login(username, password) { "
            "const token = await issueToken(username, password); return token; }"
        ),
    }
    created = client.post("/api/rag/documents", headers=_auth(users["alice_token"]), json=payload)
    assert created.status_code == 200
    doc_id = created.json()["document"]["id"]

    alice_list = client.get("/api/rag/documents", headers=_auth(users["alice_token"])).json()
    assert any(d["id"] == doc_id for d in alice_list["documents"])

    # bob 看不到 alice 的文档，直接按 id 访问或删除都返回 404
    bob_list = client.get("/api/rag/documents", headers=_auth(users["bob_token"])).json()
    assert bob_list["documents"] == []
    assert client.get(f"/api/rag/documents/{doc_id}", headers=_auth(users["bob_token"])).status_code == 404
    assert client.delete(f"/api/rag/documents/{doc_id}", headers=_auth(users["bob_token"])).status_code == 404

    # 检索同样按用户隔离
    bob_search = client.post(
        "/api/rag/search", headers=_auth(users["bob_token"]), json={"query": "login password token"}
    )
    assert bob_search.json()["results"] == []
    alice_search = client.post(
        "/api/rag/search", headers=_auth(users["alice_token"]), json={"query": "login password token"}
    )
    assert alice_search.json()["results"], "文档所有者应能检索到自己的知识片段"


def test_ai_generation_without_api_key_returns_503(users):
    resp = client.post(
        "/api/ai/generate-comments",
        headers=_auth(users["alice_token"]),
        json={"code": "function add(a, b) { return a + b; }", "language": "javascript", "task": "comment"},
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_NOT_CONFIGURED"

    # 失败的调用不记录用量、不消耗每日额度
    quota = client.get("/api/ai/quota", headers=_auth(users["alice_token"])).json()
    assert quota["quota"]["used"] == 0
    assert quota["quota"]["remaining"] == quota["quota"]["limit"]


def test_account_deletion_cascades_and_removes_access(users):
    assert client.delete("/api/auth/me", headers=_auth(users["bob_token"])).status_code == 200
    assert client.get("/api/auth/me", headers=_auth(users["bob_token"])).status_code == 401

    # bob 的注销不影响 alice 的数据
    alice_list = client.get("/api/rag/documents", headers=_auth(users["alice_token"])).json()
    assert alice_list["documents"], "注销其他用户不应删除当前用户的数据"
