"""项目级代码理解接口集成测试：上传、解析、项目隔离、级联删除与安全拒绝。"""
import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from config import PROJECT_UPLOAD_TMP_DIR
from database import get_conn
from main import app
from rate_limit import SlidingWindowLimiter
from routes import auth as auth_route
from routes import projects as projects_route
from services import project_service

client = TestClient(app)

TERMINAL = ("ready", "partial", "failed")

DEMO_FILES = [
    (
        "src/service.py",
        "\n".join([
            "def login(username, password):",
            "    validate_credentials(username)",
            "    return issue_token(username)",
            "",
            "",
            "def logout(token):",
            "    revoke_token(token)",
        ]),
    ),
    (
        "src/util.js",
        "\n".join([
            "export function normalizeName(name) {",
            "  return name.trim();",
            "}",
        ]),
    ),
    ("docs/README.md", "# 示例项目\n\n用于集成测试的说明文档。"),
]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(username: str, email: str, password: str = "Test123456") -> str:
    resp = client.post(
        "/api/auth/register", json={"username": username, "email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _zip_bytes(entries) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return buffer.getvalue()


def _upload(token: str, entries, name: str = "demo", filename: str = "demo.zip"):
    return client.post(
        "/api/projects",
        headers=_auth(token),
        files={"file": (filename, _zip_bytes(entries), "application/zip")},
        data={"name": name},
    )


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


def _scalar(sql: str, params=()):
    conn = get_conn()
    try:
        return conn.execute(sql, params).fetchone()["c"]
    finally:
        conn.close()


def _project_row(public_id: str):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM projects WHERE public_id=?", (public_id,)).fetchone()
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def _relax_limiters():
    """本模块注册与上传的次数远多于其它模块，临时放宽限流。

    限流器按客户端 IP 计数且是进程内全局状态，其它测试模块（test_api / test_auth）
    会先消耗掉默认额度；这里换成本模块专用的宽松实例，避免用例之间互相干扰，
    同时也让"限流返回 429"仍由独立用例显式覆盖。
    """
    originals = (auth_route._auth_limiter, projects_route._upload_limiter)
    auth_route._auth_limiter = SlidingWindowLimiter(1000, 60)
    projects_route._upload_limiter = SlidingWindowLimiter(1000, 60)
    try:
        yield
    finally:
        auth_route._auth_limiter, projects_route._upload_limiter = originals


@pytest.fixture(scope="module")
def users():
    return {
        "alice": _register("proj_alice", "proj_alice@example.com"),
        "bob": _register("proj_bob", "proj_bob@example.com"),
    }


def test_upload_rate_limit_returns_429(users, monkeypatch):
    monkeypatch.setattr(projects_route, "_upload_limiter", SlidingWindowLimiter(1, 60))
    assert _upload(users["alice"], DEMO_FILES).status_code == 201

    limited = _upload(users["alice"], DEMO_FILES)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"


# --- 鉴权 ---


def test_project_endpoints_require_login():
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects/whatever").status_code == 401
    assert client.delete("/api/projects/whatever").status_code == 401
    assert client.post("/api/projects/whatever/search", json={"query": "x"}).status_code == 401
    # 带文件但未登录同样被拒（鉴权在读取请求体之前完成）
    resp = client.post(
        "/api/projects",
        files={"file": ("demo.zip", _zip_bytes(DEMO_FILES), "application/zip")},
    )
    assert resp.status_code == 401


# --- 正常流程 ---


def test_upload_indexes_project_and_search_is_scoped(users):
    token = users["alice"]
    resp = _upload(token, DEMO_FILES, name="演示项目")
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["project"]["projectId"]
    assert len(project_id) == 32

    project = _wait_terminal(token, project_id)
    assert project["status"] == "ready", project
    assert project["name"] == "演示项目"
    assert project["fileCount"] == 3
    assert project["indexedFileCount"] == 3
    assert project["chunkCount"] >= 3

    files = client.get(f"/api/projects/{project_id}/files", headers=_auth(token)).json()["files"]
    paths = {item["relPath"] for item in files}
    assert paths == {"src/service.py", "src/util.js", "docs/README.md"}
    service_file = next(item for item in files if item["relPath"] == "src/service.py")
    assert service_file["language"] == "python"
    assert service_file["symbolCount"] >= 2

    detail = client.get(
        f"/api/projects/{project_id}/files/{service_file['id']}", headers=_auth(token)
    ).json()["file"]
    assert detail["structure"]["functions"], "Python 文件应返回结构分析结果"
    assert all(chunk["startLine"] >= 1 for chunk in detail["chunks"])

    search = client.post(
        f"/api/projects/{project_id}/search",
        headers=_auth(token),
        json={"query": "login username password issue_token", "topK": 5},
    )
    assert search.status_code == 200, search.text
    results = search.json()["results"]
    assert results, "项目内检索应能命中刚索引的文件"
    assert results[0]["relPath"] == "src/service.py"
    assert results[0]["startLine"] >= 1


def test_upload_cleanup_removes_work_directory(users):
    token = users["alice"]
    resp = _upload(token, DEMO_FILES, name="清理验证")
    project_id = resp.json()["project"]["projectId"]
    _wait_terminal(token, project_id)

    # 索引完成后必须删除临时工作目录
    assert not (PROJECT_UPLOAD_TMP_DIR / project_id).exists()


# --- 拒绝路径 ---


def test_upload_rejects_non_zip_and_broken_archive(users):
    token = users["alice"]

    wrong_type = _upload(token, DEMO_FILES, filename="demo.txt")
    assert wrong_type.status_code == 400
    assert wrong_type.json()["error"]["code"] == "INVALID_ARCHIVE_TYPE"

    broken = client.post(
        "/api/projects",
        headers=_auth(token),
        files={"file": ("demo.zip", b"this is not a zip archive", "application/zip")},
    )
    assert broken.status_code == 400
    assert broken.json()["error"]["code"] == "INVALID_ARCHIVE"

    empty = client.post(
        "/api/projects",
        headers=_auth(token),
        files={"file": ("demo.zip", b"", "application/zip")},
    )
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "EMPTY_ARCHIVE"


def test_upload_rejects_oversized_archive(users, monkeypatch):
    monkeypatch.setattr(projects_route, "PROJECT_MAX_ZIP_BYTES", 64)
    resp = _upload(users["alice"], DEMO_FILES)

    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "ARCHIVE_TOO_LARGE"


def test_project_limit_is_enforced(users, monkeypatch):
    monkeypatch.setattr(projects_route, "PROJECT_MAX_PER_USER", 0)
    resp = _upload(users["alice"], DEMO_FILES)

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PROJECT_LIMIT_REACHED"


def test_dangerous_entries_are_skipped_and_never_written(users):
    entries = [
        ("../evil.py", "pwned"),
        ("/etc/evil.py", "pwned"),
        (".env", "SECRET=leaked"),
        ("src/ok.py", "def ok():\n    return 1\n"),
    ]
    token = users["alice"]
    resp = _upload(token, entries, name="危险条目")
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["project"]["projectId"]

    project = _wait_terminal(token, project_id)
    assert project["status"] == "ready"
    skipped = project["detail"]["skipped"]
    assert skipped.get("unsafe_path") == 2
    assert skipped.get("sensitive_file") == 1

    files = client.get(f"/api/projects/{project_id}/files", headers=_auth(token)).json()["files"]
    assert {item["relPath"] for item in files} == {"src/ok.py"}

    # 解压产物不得出现在工作目录之外
    assert not (PROJECT_UPLOAD_TMP_DIR / ".." / "evil.py").resolve().exists()
    assert not (PROJECT_UPLOAD_TMP_DIR.parent / "evil.py").exists()
    assert not (PROJECT_UPLOAD_TMP_DIR / "evil.py").exists()


def test_archive_without_indexable_files_fails_gracefully(users):
    token = users["alice"]
    resp = _upload(token, [("logo.png", "binary"), (".env", "SECRET=1")], name="无可索引文件")
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["project"]["projectId"]

    project = _wait_terminal(token, project_id)
    assert project["status"] == "failed"
    assert project["errorMessage"]
    # 错误信息只面向用户，不暴露服务器路径或异常堆栈
    assert "Traceback" not in project["errorMessage"]
    assert "\\" not in project["errorMessage"]
    assert str(PROJECT_UPLOAD_TMP_DIR) not in project["errorMessage"]


# --- 项目隔离 ---


def test_projects_are_isolated_between_users(users):
    alice_token, bob_token = users["alice"], users["bob"]
    resp = _upload(alice_token, DEMO_FILES, name="alice 私有项目")
    project_id = resp.json()["project"]["projectId"]
    _wait_terminal(alice_token, project_id)

    # bob 对 alice 的项目完全不可见，也不能操作
    assert client.get(f"/api/projects/{project_id}", headers=_auth(bob_token)).status_code == 404
    assert client.get(f"/api/projects/{project_id}/files", headers=_auth(bob_token)).status_code == 404
    assert client.delete(f"/api/projects/{project_id}", headers=_auth(bob_token)).status_code == 404
    assert client.post(
        f"/api/projects/{project_id}/search", headers=_auth(bob_token), json={"query": "login"}
    ).status_code == 404

    bob_projects = client.get("/api/projects", headers=_auth(bob_token)).json()["projects"]
    assert all(item["projectId"] != project_id for item in bob_projects)

    # bob 自己上传另一个项目：同名关键词检索不到 alice 的文件
    bob_resp = _upload(bob_token, [("bob/own.py", "def unrelated():\n    return 0\n")], name="bob 项目")
    bob_project_id = bob_resp.json()["project"]["projectId"]
    _wait_terminal(bob_token, bob_project_id)
    bob_results = client.post(
        f"/api/projects/{bob_project_id}/search",
        headers=_auth(bob_token),
        json={"query": "login username password issue_token", "topK": 5},
    ).json()["results"]
    assert all(item["relPath"] != "src/service.py" for item in bob_results)


def test_project_chunks_do_not_leak_into_knowledge_base(users):
    token = users["alice"]
    resp = _upload(token, DEMO_FILES, name="隔离验证")
    project_id = resp.json()["project"]["projectId"]
    _wait_terminal(token, project_id)

    # 项目文件不进手动知识库
    documents = client.get("/api/rag/documents", headers=_auth(token)).json()["documents"]
    assert all(not item["title"].startswith("src/") for item in documents)

    stats = client.get("/api/rag/stats", headers=_auth(token)).json()["stats"]
    assert stats["documents"] == 0
    assert stats["chunks"] == 0

    # 知识库检索同样不会召回项目片段
    results = client.post(
        "/api/rag/search",
        headers=_auth(token),
        json={"query": "login username password issue_token"},
    ).json()["results"]
    assert results == []


# --- 生命周期 ---


def test_search_requires_ready_project(users):
    token = users["alice"]
    owner_id = client.get("/api/auth/me", headers=_auth(token)).json()["user"]["id"]
    public_id = project_service.new_public_id()
    timestamp = "2026-01-01T00:00:00+00:00"
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO projects(public_id,user_id,name,archive_name,status,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (public_id, owner_id, "未完成项目", "x.zip", project_service.STATUS_PENDING,
             timestamp, timestamp),
        )
        conn.commit()
    finally:
        conn.close()
    try:
        resp = client.post(
            f"/api/projects/{public_id}/search", headers=_auth(token), json={"query": "x"}
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PROJECT_NOT_READY"
    finally:
        conn = get_conn()
        try:
            conn.execute("DELETE FROM projects WHERE public_id=?", (public_id,))
            conn.commit()
        finally:
            conn.close()


def test_delete_project_removes_documents_and_chunks(users):
    token = users["alice"]
    resp = _upload(token, DEMO_FILES, name="待删除项目")
    project_id = resp.json()["project"]["projectId"]
    _wait_terminal(token, project_id)
    internal_id = _project_row(project_id)["id"]

    assert _scalar(
        "SELECT COUNT(*) AS c FROM rag_chunks WHERE project_id=?", (internal_id,)
    ) > 0

    assert client.delete(f"/api/projects/{project_id}", headers=_auth(token)).status_code == 200
    assert _project_row(project_id) is None
    assert _scalar("SELECT COUNT(*) AS c FROM rag_chunks WHERE project_id=?", (internal_id,)) == 0
    assert _scalar("SELECT COUNT(*) AS c FROM rag_documents WHERE project_id=?", (internal_id,)) == 0
    assert client.get(f"/api/projects/{project_id}", headers=_auth(token)).status_code == 404


def test_account_deletion_cascades_projects():
    token = _register("proj_gone", "proj_gone@example.com")
    resp = _upload(token, DEMO_FILES, name="注销级联")
    project_id = resp.json()["project"]["projectId"]
    _wait_terminal(token, project_id)
    internal_id = _project_row(project_id)["id"]

    assert client.delete("/api/auth/me", headers=_auth(token)).status_code == 200
    assert _project_row(project_id) is None
    assert _scalar("SELECT COUNT(*) AS c FROM rag_chunks WHERE project_id=?", (internal_id,)) == 0
    assert not (PROJECT_UPLOAD_TMP_DIR / project_id).exists()
