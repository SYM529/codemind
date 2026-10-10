from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import JWT_SECRET
from database import get_conn

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user: dict) -> str:
    return jwt.encode({"id": user["id"], "username": user["username"], "role": user["role"] if "role" in user.keys() else "user", "exp": datetime.now(timezone.utc) + timedelta(days=7)}, JWT_SECRET, algorithm="HS256")


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "登录状态已失效，请重新登录") from None
    except jwt.InvalidTokenError:
        raise HTTPException(401, "登录状态已失效，请重新登录") from None


def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)):
    if not creds:
        raise HTTPException(401, "请先登录后再使用此功能")
    payload = _decode_token(creds.credentials)
    conn = get_conn()
    user = conn.execute(
        "SELECT id,username,email,role,created_at,COALESCE(is_disabled,0) AS is_disabled FROM users WHERE id=?",
        (payload["id"],),
    ).fetchone()
    conn.close()
    if not user:
        raise HTTPException(401, "登录状态已失效，请重新登录")
    if user["is_disabled"]:
        raise HTTPException(
            403,
            detail={"success": False, "error": {"code": "ACCOUNT_DISABLED", "message": "账号已被管理员禁用"}},
        )
    return dict(user)


def require_admin(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user
