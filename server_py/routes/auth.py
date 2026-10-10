import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from auth import create_token, get_current_user, hash_password, verify_password
from config import ADMIN_BOOTSTRAP_USERNAME, ALLOW_PUBLIC_REGISTRATION
from database import get_conn
from models import ChangePasswordReq, LoginReq, RegisterReq
from rate_limit import SlidingWindowLimiter

router = APIRouter(prefix="/api/auth", tags=["auth"])

_auth_limiter = SlidingWindowLimiter(max_requests=10, window_seconds=60)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limited(request: Request):
    if not _auth_limiter.allow(_client_ip(request)):
        return JSONResponse(content={"success": False, "error": {"code": "RATE_LIMITED", "message": "操作过于频繁，请一分钟后再试"}}, status_code=429)
    return None


def _public_user(row) -> dict:
    return {"id": row["id"], "username": row["username"], "email": row["email"], "role": row["role"] if "role" in row.keys() else "user"}


@router.post("/register")
async def register(body: RegisterReq, request: Request):
    limited = _rate_limited(request)
    if limited:
        return limited
    if not ALLOW_PUBLIC_REGISTRATION:
        probe = get_conn()
        has_admin = probe.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
        probe.close()
        if has_admin:
            raise HTTPException(
                403,
                detail={"success": False, "error": {"code": "REGISTRATION_CLOSED", "message": "该站点已关闭公开注册，请联系管理员创建账号"}},
            )
        # 还没有管理员时，只放行引导账号，避免首个访客抢注
        if body.username != ADMIN_BOOTSTRAP_USERNAME:
            raise HTTPException(
                403,
                detail={"success": False, "error": {"code": "REGISTRATION_CLOSED", "message": f"该站点已关闭公开注册，仅允许创建引导管理员账号 {ADMIN_BOOTSTRAP_USERNAME}"}},
            )
    if not re.match(r"^[a-zA-Z0-9_]{3,20}$", body.username):
        raise HTTPException(400, detail={"success": False, "error": {"code": "INVALID_USERNAME", "message": "用户名需为 3-20 位字母、数字或下划线"}})
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", body.email):
        raise HTTPException(400, detail={"success": False, "error": {"code": "INVALID_EMAIL", "message": "请输入有效邮箱"}})
    if not body.password or len(body.password) < 6 or len(body.password) > 72:
        raise HTTPException(400, detail={"success": False, "error": {"code": "INVALID_PASSWORD", "message": "密码长度需为 6-72 位"}})

    conn = get_conn()
    exists = conn.execute("SELECT id FROM users WHERE username=? OR email=?", (body.username, body.email)).fetchone()
    if exists:
        conn.close()
        raise HTTPException(409, detail={"success": False, "error": {"code": "USER_EXISTS", "message": "用户名或邮箱已存在"}})

    pw_hash = hash_password(body.password)
    has_admin = conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
    role = "admin" if (not has_admin and body.username == ADMIN_BOOTSTRAP_USERNAME) else "user"

    cur = conn.execute(
        "INSERT INTO users(username,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
        (body.username, body.email, pw_hash, role, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    user = conn.execute("SELECT id,username,email,role FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return {"success": True, "user": _public_user(user), "token": create_token(dict(user))}


@router.post("/login")
async def login(body: LoginReq, request: Request):
    limited = _rate_limited(request)
    if limited:
        return limited
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE username=? OR email=?", (body.username, body.username)).fetchone()
    conn.close()
    if not user or not verify_password(body.password or "", user["password_hash"]):
        raise HTTPException(401, detail={"success": False, "error": {"code": "INVALID_CREDENTIALS", "message": "用户名或密码错误"}})
    if user["is_disabled"]:
        raise HTTPException(
            403,
            detail={"success": False, "error": {"code": "ACCOUNT_DISABLED", "message": "账号已被管理员禁用"}},
        )
    return {"success": True, "user": _public_user(user), "token": create_token(dict(user))}


@router.get("/registration-status")
async def registration_status():
    """前端据此决定是否展示注册入口。"""
    return {"success": True, "registrationOpen": ALLOW_PUBLIC_REGISTRATION}


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return {"success": True, "user": user}


@router.post("/change-password")
async def change_password(body: ChangePasswordReq, user=Depends(get_current_user)):
    if not body.newPassword or len(body.newPassword) < 6 or len(body.newPassword) > 72:
        raise HTTPException(400, detail={"success": False, "error": {"code": "INVALID_PASSWORD", "message": "新密码长度需为 6-72 位"}})
    conn = get_conn()
    row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
    if not row or not verify_password(body.currentPassword or "", row["password_hash"]):
        conn.close()
        raise HTTPException(400, detail={"success": False, "error": {"code": "INVALID_CURRENT_PASSWORD", "message": "当前密码错误"}})
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(body.newPassword), user["id"]))
    conn.commit()
    conn.close()
    return {"success": True, "message": "密码修改成功，请重新登录"}


@router.delete("/me")
async def delete_account(user=Depends(get_current_user)):
    conn = get_conn()
    uid = user["id"]
    conn.execute("DELETE FROM feedback WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM evaluations WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM usage_records WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM generations WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM rag_chunks WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM rag_documents WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM ai_cache WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "账户及相关数据已删除"}
