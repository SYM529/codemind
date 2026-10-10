"""管理员用户管理测试：用户列表、代建账号、禁用/启用、删除，以及注册开关与守卫规则。"""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Admin123456"


def _register(username, email, password="Test123456"):
    return client.post("/api/auth/register", json={"username": username, "email": email, "password": password})


def _login(username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def admin_token():
    """复用已有管理员；不存在时按引导机制创建，保证与其他测试模块顺序无关。"""
    resp = _register(ADMIN_USERNAME, "admin@example.com", ADMIN_PASSWORD)
    if resp.status_code == 409:
        resp = _login(ADMIN_USERNAME, ADMIN_PASSWORD)
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["role"] == "admin"
    return resp.json()["token"]


def test_admin_users_list_returns_rows(admin_token):
    resp = client.get("/api/admin/users", headers=_auth(admin_token))
    assert resp.status_code == 200
    users = resp.json()["users"]
    assert any(u["username"] == ADMIN_USERNAME for u in users)
    for u in users:
        assert {"id", "username", "role", "disabled", "generations"} <= set(u)


def test_disable_blocks_access_and_restores_when_enabled(admin_token):
    headers = _auth(admin_token)
    created = client.post(
        "/api/admin/users",
        headers=headers,
        json={"username": "um_target", "email": "um_target@example.com", "password": "Target123456"},
    )
    assert created.status_code == 200, created.text
    uid = created.json()["user"]["id"]
    token = _login("um_target", "Target123456").json()["token"]

    disabled = client.patch(f"/api/admin/users/{uid}", headers=headers, json={"disabled": True})
    assert disabled.status_code == 200
    assert disabled.json()["user"]["disabled"] is True

    me = client.get("/api/auth/me", headers=_auth(token))
    assert me.status_code == 403
    assert me.json()["error"]["code"] == "ACCOUNT_DISABLED"
    blocked_login = _login("um_target", "Target123456")
    assert blocked_login.status_code == 403
    assert blocked_login.json()["error"]["code"] == "ACCOUNT_DISABLED"

    enabled = client.patch(f"/api/admin/users/{uid}", headers=headers, json={"disabled": False})
    assert enabled.json()["user"]["disabled"] is False
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 200

    deleted = client.delete(f"/api/admin/users/{uid}", headers=headers)
    assert deleted.status_code == 200
    remaining = client.get("/api/admin/users", headers=headers).json()["users"]
    assert all(u["id"] != uid for u in remaining)


def test_admin_cannot_disable_or_delete_self(admin_token):
    headers = _auth(admin_token)
    me = client.get("/api/auth/me", headers=headers).json()["user"]

    disabled = client.patch(f"/api/admin/users/{me['id']}", headers=headers, json={"disabled": True})
    assert disabled.status_code == 400
    assert disabled.json()["error"]["code"] == "CANNOT_DISABLE_SELF"

    deleted = client.delete(f"/api/admin/users/{me['id']}", headers=headers)
    assert deleted.status_code == 400
    assert deleted.json()["error"]["code"] == "CANNOT_DELETE_SELF"


def test_last_admin_cannot_be_demoted(admin_token):
    """把其余管理员都降级后，最后一个管理员不允许再被取消管理员身份。"""
    headers = _auth(admin_token)
    me = client.get("/api/auth/me", headers=headers).json()["user"]

    users = client.get("/api/admin/users", headers=headers).json()["users"]
    for u in users:
        if u["role"] == "admin" and u["id"] != me["id"]:
            resp = client.patch(f"/api/admin/users/{u['id']}", headers=headers, json={"role": "user"})
            assert resp.status_code == 200, resp.text

    resp = client.patch(f"/api/admin/users/{me['id']}", headers=headers, json={"role": "user"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "LAST_ADMIN_REQUIRED"
    # 自身仍保持管理员身份，不会被意外降级
    assert client.get("/api/auth/me", headers=headers).json()["user"]["role"] == "admin"


def test_closed_registration_only_allows_admin_created_accounts(admin_token, monkeypatch):
    monkeypatch.setattr("routes.auth.ALLOW_PUBLIC_REGISTRATION", False)
    headers = _auth(admin_token)

    assert client.get("/api/auth/registration-status").json()["registrationOpen"] is False

    blocked = _register("um_outsider", "um_outsider@example.com")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "REGISTRATION_CLOSED"

    created = client.post(
        "/api/admin/users",
        headers=headers,
        json={"username": "um_created", "email": "um_created@example.com", "password": "Created123456"},
    )
    assert created.status_code == 200, created.text
    client.delete(f"/api/admin/users/{created.json()['user']['id']}", headers=headers)
