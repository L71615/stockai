"""StockAI — 设置 API（SMTP 配置等）"""

from fastapi import APIRouter
from pydantic import BaseModel

from services.email_service import (
    get_smtp_settings,
    save_smtp_settings,
    test_smtp_connection,
)

router = APIRouter()


class SmtpBody(BaseModel):
    host: str
    port: int = 465
    user: str
    password: str


@router.get("/api/settings/smtp")
def api_get_smtp():
    """获取 SMTP 配置（密码脱敏）"""
    cfg = get_smtp_settings()
    return {"config": cfg}


@router.put("/api/settings/smtp")
def api_save_smtp(body: SmtpBody):
    """保存 SMTP 配置"""
    save_smtp_settings(body.host, body.port, body.user, body.password)
    return {"ok": True}


@router.post("/api/settings/smtp/test")
def api_test_smtp(body: SmtpBody):
    """发送测试邮件"""
    ok, err = test_smtp_connection(body.host, body.port, body.user, body.password)
    return {"ok": ok, "error": err}
