"""认证路由 — JWT 登录 + IP 限流（不开放注册）"""

import time
import threading
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from passlib.hash import bcrypt

from database import query_one
from config import JWT_SECRET, JWT_EXPIRES, LOGIN_RATE_LIMIT, LOGIN_LOCK_MINUTES

router = APIRouter()

# ── IP 限流（内存）──
_rate_lock = threading.Lock()
_rate_store: dict[str, list[float]] = {}  # ip → [fail_timestamp, ...]


def _check_rate(ip: str) -> tuple[bool, str]:
    """检查 IP 是否被限流。返回 (allowed, reason)"""
    now = time.time()
    window = LOGIN_LOCK_MINUTES * 60

    with _rate_lock:
        failures = _rate_store.get(ip, [])
        # 清理过期记录
        failures = [t for t in failures if now - t < window]
        _rate_store[ip] = failures

        if len(failures) >= LOGIN_RATE_LIMIT:
            remaining = int(window - (now - failures[0]))
            minutes = max(1, remaining // 60 + 1)
            return False, f"登录失败次数过多，请 {minutes} 分钟后重试"

        return True, ""


def _record_fail(ip: str):
    """记录一次失败"""
    with _rate_lock:
        _rate_store.setdefault(ip, []).append(time.time())


def _clear_fails(ip: str):
    """登录成功后清除失败记录"""
    with _rate_lock:
        _rate_store.pop(ip, None)


# ── 请求模型 ──
class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(req: LoginRequest, request: Request):
    """管理员登录，返回 JWT token"""
    ip = request.client.host if request.client else "unknown"

    # 1. 限流检查
    allowed, reason = _check_rate(ip)
    if not allowed:
        raise HTTPException(429, reason)

    # 2. 验证账号
    user = query_one("SELECT id, username, password FROM users WHERE email = ?", (req.email,))
    if not user or not bcrypt.verify(req.password, user["password"]):
        _record_fail(ip)
        raise HTTPException(401, "邮箱或密码错误")

    # 3. 签发 JWT
    _clear_fails(ip)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "iat": now,
        "exp": now + timedelta(seconds=JWT_EXPIRES),
    }
    token = pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")

    return {
        "token": token,
        "username": user["username"],
        "expires_in": JWT_EXPIRES,
        "message": "登录成功",
    }


# 注册接口已关闭（系统仅允许唯一管理员账号，由 .env 预设）
@router.post("/register")
def register():
    raise HTTPException(403, "注册已关闭，请联系管理员")


@router.get("/profile")
def profile():
    """获取当前用户信息（单用户模式）"""
    user = query_one(
        "SELECT id, username, email, phone, avatar_url, created_at FROM users WHERE id = 1"
    )
    if not user:
        raise HTTPException(404, "用户不存在")
    return user
