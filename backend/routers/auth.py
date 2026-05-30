"""认证路由"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from passlib.hash import bcrypt

from database import query_one, execute

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


@router.post("/login")
def login(req: LoginRequest):
    user = query_one("SELECT * FROM users WHERE email = ?", (req.email,))
    if not user:
        raise HTTPException(401, "邮箱或密码错误")
    if not bcrypt.verify(req.password, user["password"]):
        raise HTTPException(401, "邮箱或密码错误")
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "message": "登录成功",
    }


@router.post("/register")
def register(req: RegisterRequest):
    try:
        hashed = bcrypt.hash(req.password)
        result = execute(
            "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
            (req.username, req.email, hashed),
        )
        return {"id": result["lastrowid"], "message": "注册成功"}
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(409, "用户名或邮箱已存在")
        raise HTTPException(500, "注册失败，请重试")


@router.get("/profile")
def profile():
    user = query_one(
        "SELECT id, username, email, phone, avatar_url, created_at FROM users WHERE id = 1"
    )
    if not user:
        raise HTTPException(404, "用户不存在")
    return user
