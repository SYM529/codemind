import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from auth import hash_password, require_admin
from database import get_conn
from models import AdminCreateUserReq, AdminUpdateUserReq
from services import project_service

router = APIRouter(prefix="/api/admin", tags=["admin"])

_USER_COLUMNS = (
    "u.id,u.username,u.email,u.role,u.created_at,COALESCE(u.is_disabled,0) AS is_disabled,"
    "(SELECT COUNT(*) FROM generations g WHERE g.user_id=u.id) AS generations"
)


def _delete_user_data(conn, uid: int) -> list:
    """删除用户及其全部关联数据，范围与个人注销接口保持一致。

    返回该用户的项目标识，供调用方在事务提交后清理上传工作目录。
    """
    public_ids = [
        row["public_id"]
        for row in conn.execute("SELECT public_id FROM projects WHERE user_id=?", (uid,)).fetchall()
    ]
    conn.execute("DELETE FROM feedback WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM evaluations WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM usage_records WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM generations WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM rag_chunks WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM rag_documents WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM ai_cache WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM projects WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    return public_ids


@router.get("/metrics")
async def metrics(user=Depends(require_admin)):
    conn = get_conn()
    users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    usage = conn.execute(
        "SELECT COUNT(*) AS requests,"
        "COALESCE(SUM(estimated_input_tokens),0) AS inputTokens,"
        "COALESCE(SUM(estimated_output_tokens),0) AS outputTokens,"
        "COALESCE(SUM(estimated_cost_usd),0) AS costUsd"
        " FROM usage_records"
    ).fetchone()
    fb = conn.execute(
        "SELECT COUNT(*) AS total,"
        "COALESCE(SUM(CASE WHEN rating='helpful' THEN 1 ELSE 0 END),0) AS helpful"
        " FROM feedback"
    ).fetchone()
    ev = conn.execute(
        "SELECT COUNT(*) AS generations,"
        "COALESCE(AVG(function_coverage),0) AS functionCoverage,"
        "COALESCE(AVG(valid_line_rate),0) AS validLineRate,"
        "COALESCE(AVG(duration_ms),0) AS durationMs"
        " FROM evaluations"
    ).fetchone()
    daily = conn.execute(
        "SELECT substr(created_at,1,10) AS date, COUNT(*) AS requests,"
        "COALESCE(SUM(estimated_cost_usd),0) AS costUsd"
        " FROM usage_records GROUP BY date ORDER BY date DESC LIMIT 7"
    ).fetchall()
    conn.close()

    total = fb["total"]
    helpful_rate = None if total == 0 else round(fb["helpful"] / total, 4)
    return {
        "success": True,
        "metrics": {
            "users": users,
            "usage": {
                "requests": usage["requests"],
                "inputTokens": usage["inputTokens"],
                "outputTokens": usage["outputTokens"],
                "costUsd": usage["costUsd"],
            },
            "feedback": {"total": total, "helpfulRate": helpful_rate},
            "evaluations": {
                "generations": ev["generations"],
                "functionCoverage": round(ev["functionCoverage"], 4),
                "validLineRate": round(ev["validLineRate"], 4),
                "durationMs": round(ev["durationMs"]),
            },
            "projects": project_service.project_counts_for_admin(),
            "daily": [dict(r) for r in daily],
        },
    }


def _user_row(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "createdAt": row["created_at"],
        "disabled": bool(row["is_disabled"]),
        "generations": row["generations"],
    }


@router.get("/users")
async def list_users(user=Depends(require_admin)):
    conn = get_conn()
    rows = conn.execute(f"SELECT {_USER_COLUMNS} FROM users u ORDER BY u.id").fetchall()
    conn.close()
    return {"success": True, "users": [_user_row(r) for r in rows]}


@router.post("/users")
async def create_user(body: AdminCreateUserReq, user=Depends(require_admin)):
    """管理员代为创建账号，不受公开注册开关限制。"""
    username = (body.username or "").strip()
    email = (body.email or "").strip()
    if not re.match(r"^[a-zA-Z0-9_]{3,20}$", username):
        raise HTTPException(400, detail={"success": False, "error": {"code": "INVALID_USERNAME", "message": "用户名需为 3-20 位字母、数字或下划线"}})
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        raise HTTPException(400, detail={"success": False, "error": {"code": "INVALID_EMAIL", "message": "请输入有效邮箱"}})
    if not body.password or len(body.password) < 6 or len(body.password) > 72:
        raise HTTPException(400, detail={"success": False, "error": {"code": "INVALID_PASSWORD", "message": "密码长度需为 6-72 位"}})
    if body.role not in ("user", "admin"):
        raise HTTPException(400, detail={"success": False, "error": {"code": "INVALID_ROLE", "message": "角色只能是 user 或 admin"}})

    conn = get_conn()
    exists = conn.execute("SELECT id FROM users WHERE username=? OR email=?", (username, email)).fetchone()
    if exists:
        conn.close()
        raise HTTPException(409, detail={"success": False, "error": {"code": "USER_EXISTS", "message": "用户名或邮箱已存在"}})
    cur = conn.execute(
        "INSERT INTO users(username,email,password_hash,role,is_disabled,created_at) VALUES(?,?,?,?,0,?)",
        (username, email, hash_password(body.password), body.role, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return {"success": True, "user": {"id": cur.lastrowid, "username": username, "email": email, "role": body.role, "disabled": False, "generations": 0}}


@router.patch("/users/{user_id}")
async def update_user(user_id: int, body: AdminUpdateUserReq, user=Depends(require_admin)):
    """修改角色或禁用状态：不能把自己锁在系统外，也不能取消最后一个管理员。"""
    if body.role is not None and body.role not in ("user", "admin"):
        raise HTTPException(400, detail={"success": False, "error": {"code": "INVALID_ROLE", "message": "角色只能是 user 或 admin"}})

    conn = get_conn()
    target = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    if not target:
        conn.close()
        raise HTTPException(404, detail={"success": False, "error": {"code": "USER_NOT_FOUND", "message": "用户不存在"}})

    if user_id == user["id"] and body.disabled:
        conn.close()
        raise HTTPException(400, detail={"success": False, "error": {"code": "CANNOT_DISABLE_SELF", "message": "不能禁用自己，否则会被锁在系统外"}})

    admin_count = conn.execute("SELECT COUNT(*) AS c FROM users WHERE role='admin'").fetchone()["c"]
    losing_admin = target["role"] == "admin" and (body.disabled is True or (body.role is not None and body.role != "admin"))
    if losing_admin and admin_count <= 1:
        conn.close()
        raise HTTPException(400, detail={"success": False, "error": {"code": "LAST_ADMIN_REQUIRED", "message": "至少需要保留一个管理员账号"}})

    updates, params = [], []
    if body.disabled is not None:
        updates.append("is_disabled=?")
        params.append(1 if body.disabled else 0)
    if body.role is not None:
        updates.append("role=?")
        params.append(body.role)
    if updates:
        params.append(user_id)
        conn.execute(f"UPDATE users SET {','.join(updates)} WHERE id=?", tuple(params))
        conn.commit()
    row = conn.execute(f"SELECT {_USER_COLUMNS} FROM users u WHERE u.id=?", (user_id,)).fetchone()
    conn.close()
    return {"success": True, "user": _user_row(row)}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, user=Depends(require_admin)):
    conn = get_conn()
    target = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    if not target:
        conn.close()
        raise HTTPException(404, detail={"success": False, "error": {"code": "USER_NOT_FOUND", "message": "用户不存在"}})
    if user_id == user["id"]:
        conn.close()
        raise HTTPException(400, detail={"success": False, "error": {"code": "CANNOT_DELETE_SELF", "message": "不能删除自己的账号，如需注销请使用个人中心"}})
    admin_count = conn.execute("SELECT COUNT(*) AS c FROM users WHERE role='admin'").fetchone()["c"]
    if target["role"] == "admin" and admin_count <= 1:
        conn.close()
        raise HTTPException(400, detail={"success": False, "error": {"code": "LAST_ADMIN_REQUIRED", "message": "至少需要保留一个管理员账号"}})

    public_ids = _delete_user_data(conn, user_id)
    conn.commit()
    conn.close()
    for public_id in public_ids:
        project_service.discard_upload_dir(project_service.upload_dir_for(public_id))
    return {"success": True, "message": "用户及其相关数据已删除"}
