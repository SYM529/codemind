"""项目级问答接口测试：跨项目隔离、来源引用、空检索、异常处理与流式输出。"""
import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from database import get_conn
from main import app
from rate_limit import SlidingWindowLimiter
from routes import projects as projects_route
from services import ai_qa_service, project_service

client = TestClient(app)

TERMINAL = ("ready", "partial", "failed")

LOGIN_CODE = "\n".join([
    "def login(username, password):",
    "    validate_credentials(username, password)",
    "    return issue_token(username)",
])
UNRELATED_CODE = "\n".join([
    "def render_sprite(sprite):",
    "    return draw_pixels(sprite)",
])


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(username: str, email: str, password: str = "Test123456") -> str:
    resp = client.post(
        "/api/auth/register", json={"username": username, "email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _user_id(token: str) -> int:
    return client.get("/api/auth/me", headers=_auth(token)).json()["user"]["id"]


def _zip_bytes(entries) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return buffer.getvalue()


def _upload(token: str, entries, name: str = "qa") -> str:
    resp = client.post(
        "/api/projects",
        headers=_auth(token),
        files={"file": ("qa.zip", _zip_bytes(entries), "application/zip")},
        data={"name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["project"]["projectId"]


def _wait_terminal(token: str, project_id: str, attempts: int = 40) -> dict:
    project = {}
    for _ in range(attempts):
        resp = client.get(f"/api/projects/{project_id}", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        project = resp.json()["project"]
        if project["status"] in TERMINAL:
            return project
        time.sleep(0.05)
    return project


def _ask(token: str, project_id: str, question: str):
    return client.post(
        f"/api/projects/{project_id}/ask",
        headers=_auth(token),
        json={"question": question, "topK": 4},
    )


def _parse_sse(text: str):
    """解析 text/event-stream 响应体，返回 [(event_name, payload), ...]。"""
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = None
        payload = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                payload = json.loads(line[len("data: "):])
        if event_name and payload is not None:
            events.append((event_name, payload))
    return events


def _usage_count(user_id: int) -> int:
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM usage_records WHERE user_id=?", (user_id,)
        ).fetchone()["c"]
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def _relax_limiters():
    """本模块连续注册/上传/提问较多，放宽共享的 IP 限流，避免与其它测试模块互相干扰。"""
    from routes import auth as auth_route

    originals = (
        auth_route._auth_limiter,
        projects_route._upload_limiter,
        projects_route._qa_limiter,
    )
    auth_route._auth_limiter = SlidingWindowLimiter(1000, 60)
    projects_route._upload_limiter = SlidingWindowLimiter(1000, 60)
    projects_route._qa_limiter = SlidingWindowLimiter(1000, 60)
    try:
        yield
    finally:
        auth_route._auth_limiter, projects_route._upload_limiter, projects_route._qa_limiter = originals


@pytest.fixture(autouse=True)
def _generous_quota(monkeypatch):
    """默认不触发每日额度；额度超限由专门用例显式覆盖。"""
    monkeypatch.setattr(
        projects_route,
        "_get_daily_quota",
        lambda user_id: {"limit": 1000, "used": 0, "remaining": 1000, "resetAt": 0},
    )


def test_ask_requires_login():
    resp = client.post("/api/projects/whatever/ask", json={"question": "login"})
    assert resp.status_code == 401


def test_ask_requires_ready_project():
    token = _register("qa_pending", "qa_pending@example.com")
    uid = _user_id(token)
    public_id = project_service.new_public_id()
    timestamp = "2026-01-01T00:00:00+00:00"
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO projects(public_id,user_id,name,archive_name,status,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (public_id, uid, "未完成", "x.zip", project_service.STATUS_PENDING, timestamp, timestamp),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        resp = _ask(token, public_id, "登录在哪实现")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PROJECT_NOT_READY"
    finally:
        conn = get_conn()
        try:
            conn.execute("DELETE FROM projects WHERE public_id=?", (public_id,))
            conn.commit()
        finally:
            conn.close()


def test_ask_returns_insufficient_evidence_without_model_call():
    token = _register("qa_insuff", "qa_insuff@example.com")
    project_id = _upload(token, [("src/sprite.py", UNRELATED_CODE)])
    _wait_terminal(token, project_id)
    uid = _user_id(token)

    resp = _ask(token, project_id, "database migration strategy")
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[-1][0] == "complete", events
    data = events[-1][1]
    assert data["insufficientEvidence"] is True
    assert data["citations"] == []
    assert "无法确定" in data["answer"]
    # 证据不足不调用模型，不产生用量（测试环境无 API Key，若调用模型会走到 error 事件）
    assert _usage_count(uid) == 0


def test_ask_streams_answer_and_citations(monkeypatch):
    token = _register("qa_stream", "qa_stream@example.com")
    project_id = _upload(token, [("src/auth/service.py", LOGIN_CODE)])
    _wait_terminal(token, project_id)
    uid = _user_id(token)

    captured = {}

    async def fake_stream(question, context_text, on_token=None):
        captured["question"] = question
        captured["context"] = context_text
        if on_token:
            on_token("登录")
            on_token("流程在 ")
        return {
            "answer": "登录流程在 login 中实现",
            "durationMs": 3,
            "usage": {
                "model": "deepseek-chat",
                "estimatedInputTokens": 12,
                "estimatedOutputTokens": 5,
                "source": "estimated",
            },
        }

    monkeypatch.setattr(ai_qa_service, "stream_answer", fake_stream)

    resp = _ask(token, project_id, "login password")
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    names = [name for name, _ in events]
    assert "token" in names
    assert "complete" in names

    tokens = [data["token"] for name, data in events if name == "token"]
    assert "".join(tokens) == "登录流程在 "

    data = events[-1][1]
    assert data["insufficientEvidence"] is False
    assert data["answer"] == "登录流程在 login 中实现"
    assert data["citations"], "回答应带真实检索来源"
    assert data["citations"][0]["relPath"] == "src/auth/service.py"
    assert data["citations"][0]["symbolName"] == "login"
    assert data["citations"][0]["startLine"] >= 1
    assert "login" in captured["context"]
    # 成功调用会记录用量
    assert _usage_count(uid) == 1


def test_ask_is_scoped_to_own_project(monkeypatch):
    alice = _register("qa_alice", "qa_alice@example.com")
    bob = _register("qa_bob", "qa_bob@example.com")
    alice_project = _upload(alice, [("alice_auth.py", LOGIN_CODE)])
    bob_project = _upload(bob, [("bob_auth.py", LOGIN_CODE)])
    _wait_terminal(alice, alice_project)
    _wait_terminal(bob, bob_project)

    captured = {}

    async def fake_stream(question, context_text, on_token=None):
        captured["context"] = context_text
        return {
            "answer": "ok",
            "durationMs": 1,
            "usage": {
                "model": "deepseek-chat",
                "estimatedInputTokens": 5,
                "estimatedOutputTokens": 2,
                "source": "estimated",
            },
        }

    monkeypatch.setattr(ai_qa_service, "stream_answer", fake_stream)

    resp = _ask(bob, bob_project, "login")
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[-1][0] == "complete"

    assert "bob_auth.py" in captured["context"]
    assert "alice_auth.py" not in captured["context"]
    citations = events[-1][1]["citations"]
    assert citations
    assert all("bob_auth.py" in item["relPath"] for item in citations)


def test_ask_without_api_key_returns_error_event():
    token = _register("qa_nokey", "qa_nokey@example.com")
    project_id = _upload(token, [("src/auth.py", LOGIN_CODE)])
    _wait_terminal(token, project_id)
    uid = _user_id(token)

    resp = _ask(token, project_id, "login")
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "AI_NOT_CONFIGURED"
    # 模型调用失败不消耗额度
    assert _usage_count(uid) == 0


def test_ask_rate_limit_returns_429(monkeypatch):
    token = _register("qa_rl", "qa_rl@example.com")
    project_id = _upload(token, [("src/auth.py", LOGIN_CODE)])
    _wait_terminal(token, project_id)

    monkeypatch.setattr(projects_route, "_qa_limiter", SlidingWindowLimiter(1, 60))
    assert _ask(token, project_id, "login").status_code == 200

    limited = _ask(token, project_id, "login")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"


def test_ask_quota_exceeded_returns_429(monkeypatch):
    token = _register("qa_quota", "qa_quota@example.com")
    project_id = _upload(token, [("src/auth.py", LOGIN_CODE)])
    _wait_terminal(token, project_id)

    monkeypatch.setattr(
        projects_route,
        "_get_daily_quota",
        lambda user_id: {"limit": 1, "used": 1, "remaining": 0, "resetAt": 0},
    )
    resp = _ask(token, project_id, "login")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "DAILY_QUOTA_EXCEEDED"


def test_ask_reports_embedding_dimension_mismatch_clearly():
    """切换 Embedding 模型后，旧项目必须给出可执行的提示，而不是笼统的“无法确定”。"""
    token = _register("qa_dim", "qa_dim@example.com")
    uid = _user_id(token)
    public_id = project_service.new_public_id()
    project_service.create_project(uid, public_id, "维度不一致", "dim.zip")
    row = project_service.fetch_project_row(uid, public_id)
    timestamp = "2026-01-01T00:00:00+00:00"

    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO rag_documents(user_id,title,source,language,char_count,chunk_count,"
            "project_id,rel_path,line_count,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (uid, "legacy.py", "project", "python", 20, 1, row["id"], "legacy.py", 1, timestamp),
        )
        document_id = conn.execute(
            "SELECT id FROM rag_documents WHERE project_id=?", (row["id"],)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO rag_chunks(document_id,user_id,chunk_index,content,embedding_json,"
            "project_id,rel_path,language,start_line,end_line,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (document_id, uid, 0, "def login(): pass", json.dumps([0.1] * 32),
             row["id"], "legacy.py", "python", 1, 1, timestamp),
        )
        conn.execute(
            "UPDATE projects SET status='ready', file_count=1, indexed_file_count=1, chunk_count=1"
            " WHERE id=?",
            (row["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        resp = _ask(token, public_id, "login")
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        assert events[-1][0] == "error", events
        assert events[-1][1]["code"] == "EMBEDDING_DIM_MISMATCH"
        assert "重新上传" in events[-1][1]["message"]
    finally:
        conn = get_conn()
        try:
            conn.execute("DELETE FROM rag_chunks WHERE project_id=?", (row["id"],))
            conn.execute("DELETE FROM rag_documents WHERE project_id=?", (row["id"],))
            conn.execute("DELETE FROM projects WHERE id=?", (row["id"],))
            conn.commit()
        finally:
            conn.close()
