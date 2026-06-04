"""StockAI — 设置 API（AI / SMTP 配置等）"""

from fastapi import APIRouter
from pydantic import BaseModel

from services.email_service import (
    get_smtp_settings,
    save_smtp_settings,
    test_smtp_connection,
)
from services.ai_service import _load_stored_ai_config, save_stored_ai_config

router = APIRouter()


class AiConfigBody(BaseModel):
    provider: str = "minimax"
    api_key: str = ""
    model: str = ""
    base_url: str = ""


class MultiAiConfigBody(BaseModel):
    configs: dict = {}  # {"minimax": {"api_key":"...","model":"..."}, "deepseek": {...}}


@router.get("/api/settings/ai-config")
def api_get_ai_config():
    """获取旧版单供应商 AI 配置（兼容）"""
    cfg = _load_stored_ai_config()
    if cfg.get("api_key"):
        key = cfg["api_key"]
        cfg["api_key"] = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
    return {"config": cfg}


@router.put("/api/settings/ai-config")
def api_save_ai_config(body: AiConfigBody):
    """保存旧版单供应商 AI 配置（兼容）"""
    save_stored_ai_config(body.model_dump())
    return {"ok": True}


@router.get("/api/settings/ai-configs")
def api_get_all_ai_configs():
    """获取所有已保存的 AI 供应商配置（api_key 脱敏）"""
    cfg = _load_stored_ai_config()
    result = {}
    if isinstance(cfg, dict):
        for provider, c in cfg.items():
            if isinstance(c, dict):
                key = c.get("api_key", "")
                result[provider] = {
                    "api_key": (key[:4] + "****" + key[-4:]) if len(key) > 8 else ("****" if key else ""),
                    "model": c.get("model", ""),
                    "base_url": c.get("base_url", ""),
                }
    # 旧版单配置兼容
    if not result and cfg.get("api_key"):
        result[cfg.get("provider", "minimax")] = {
            "api_key": "****",
            "model": cfg.get("model", ""),
            "base_url": cfg.get("base_url", ""),
        }
    return {"configs": result}


@router.put("/api/settings/ai-configs")
def api_save_all_ai_configs(body: MultiAiConfigBody):
    """保存多个 AI 供应商配置"""
    save_stored_ai_config(body.configs)
    return {"ok": True, "count": len(body.configs)}


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
