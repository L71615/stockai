"""StockAI — AI 模型服务

支持的供应商：MiniMax / Claude / OpenAI / OpenAI 兼容
"""

import logging

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

logger = logging.getLogger("stockai")

from config import (
    AI_PROVIDER, CLAUDE_API_KEY, CLAUDE_MODEL,
    OPENAI_API_KEY, MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_BASE_URL,
    DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL,
    XIAOMI_API_KEY, XIAOMI_MODEL, XIAOMI_BASE_URL,
)

_openai_clients: dict[str, AsyncOpenAI] = {}
_anthropic_client: AsyncAnthropic | None = None


def _get_openai_client(api_key: str, base_url: str) -> AsyncOpenAI:
    cache_key = f"{api_key}@{base_url}"
    if cache_key not in _openai_clients:
        _openai_clients[cache_key] = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return _openai_clients[cache_key]


_last_anthropic_key: str = ""

def _get_anthropic_client(api_key: str) -> AsyncAnthropic:
    global _anthropic_client, _last_anthropic_key
    if _anthropic_client is None or api_key != _last_anthropic_key:
        _anthropic_client = AsyncAnthropic(api_key=api_key)
        _last_anthropic_key = api_key
    return _anthropic_client



async def _chat_openai_compatible(
    messages: list[dict], *, api_key: str, base_url: str, model: str,
    system_prompt: str = "",
) -> str:
    client = _get_openai_client(api_key, base_url)
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)
    response = await client.chat.completions.create(model=model, messages=full_messages)
    return response.choices[0].message.content


PROVIDER_DEFAULTS = {
    "minimax":  (MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_BASE_URL, "MiniMax"),
    "deepseek": (DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL, "DeepSeek"),
    "xiaomi":   (XIAOMI_API_KEY, XIAOMI_MODEL, XIAOMI_BASE_URL, "小米"),
    "openai":   (OPENAI_API_KEY, "gpt-4o", "https://api.openai.com/v1", "OpenAI"),
}


async def _chat_openai_provider(
    messages: list[dict], provider_key: str,
    *, api_key: str = "", model: str = "", system_prompt: str = "",
) -> str:
    """通用 OpenAI 兼容供应商调用"""
    env_key, default_model, base_url, name = PROVIDER_DEFAULTS[provider_key]
    key = api_key or env_key
    if not key:
        return f"（未配置 {name} API Key，请在设置页配置）"
    m = model or default_model
    try:
        return await _chat_openai_compatible(messages, api_key=key, base_url=base_url, model=m, system_prompt=system_prompt)
    except Exception as e:
        return f"（{name} API 调用失败: {e}）"


async def chat_with_claude(messages: list[dict], *, system_prompt: str = "", api_key: str = "", model: str = "") -> str:
    key = api_key or CLAUDE_API_KEY
    if not key:
        return "（未配置 Claude API Key，请在设置页配置）"
    m = model or CLAUDE_MODEL
    try:
        client = _get_anthropic_client(key)
        response = await client.messages.create(
            model=m, max_tokens=4096,
            system=system_prompt, messages=messages,
        )
        if response.content and len(response.content) > 0:
            return response.content[0].text
        return "（Claude 返回空响应）"
    except ImportError:
        return "（请先安装 anthropic SDK: pip install anthropic）"
    except Exception as e:
        return f"（Claude API 调用失败: {e}）"


def get_default_provider() -> str:
    """获取用户保存的默认 AI 供应商

    优先级：settings 表 ai_config.default_provider → 环境变量 AI_PROVIDER → "deepseek"
    当 function_providers 未配置时，所有功能回退到此默认值。
    """
    try:
        from database import query_one
        import json as _json
        row = query_one("SELECT value FROM settings WHERE key = 'ai_config'")
        if row and row.get("value"):
            cfg = _json.loads(row["value"])
            if isinstance(cfg, dict) and cfg.get("default_provider"):
                return cfg["default_provider"]
    except Exception:
        logger.debug("get_default_provider: settings read failed, using env fallback")
    return AI_PROVIDER or "deepseek"


def get_provider_for_function(function_key: str) -> str:
    """按功能解析供应商 — 读取 settings 表 function_providers 映射

    优先级：function_providers[function_key] → default_provider → 环境变量 → "deepseek"
    用户在设置页可以为每个 AI 功能独立指定供应商。
    """
    try:
        from database import query_one
        import json as _json
        row = query_one("SELECT value FROM settings WHERE key = 'ai_config'")
        if row and row.get("value"):
            cfg = _json.loads(row["value"])
            if isinstance(cfg, dict):
                fp = cfg.get("function_providers", {})
                if isinstance(fp, dict) and function_key in fp and fp[function_key]:
                    return fp[function_key]
    except Exception:
        logger.debug("get_provider_for_function: settings read failed")
    return get_default_provider()


async def ai_chat(
    message: str,
    conversation_history: list[dict] = None,
    *,
    provider: str = "",
    function: str = "",
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    system_prompt: str = "",
) -> str:
    """统一的 AI 对话入口（多供应商调度）

    provider 为空时自动用 get_default_provider()（用户设置 > 环境变量）。
    如果提供了 function 参数，优先从 function_providers 映射查找供应商。
    api_key/model 为空时，自动从 settings 表读取该供应商的保存配置。
    """
    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": message})

    # 参数为空时，从设置页读取用户保存的配置
    if not provider and function:
        provider = get_provider_for_function(function)
    p = provider or get_default_provider()
    if not api_key or not model:
        stored = _load_stored_ai_config(p)
        api_key = api_key or stored.get("api_key", "")
        model = model or stored.get("model", "")
        base_url = base_url or stored.get("base_url", "")

    if p in PROVIDER_DEFAULTS:
        return await _chat_openai_provider(messages, p, api_key=api_key, model=model, system_prompt=system_prompt)
    elif p == "claude":
        return await chat_with_claude(messages, api_key=api_key, model=model, system_prompt=system_prompt)
    elif p == "custom":
        if not base_url:
            return "（使用自定义供应商请填写 Base URL）"
        m = model or "gpt-4o"
        try:
            return await _chat_openai_compatible(messages, api_key=api_key, base_url=base_url, model=m, system_prompt=system_prompt)
        except Exception as e:
            return f"（自定义 API 调用失败: {e}）"
    else:
        return f"（不支持的 AI 供应商: {p}）"


def _decrypt_dict(cfg: dict) -> dict:
    """递归解密 dict 中所有 api_key 字段"""
    from services.crypto_service import decrypt
    result = {}
    for k, v in cfg.items():
        if k == "api_key" and isinstance(v, str) and v:
            try:
                result[k] = decrypt(v.encode())
            except Exception:
                result[k] = v  # 无法解密则保留原值（兼容旧数据）
        elif isinstance(v, dict):
            result[k] = _decrypt_dict(v)
        else:
            result[k] = v
    return result


def _encrypt_dict(cfg: dict) -> dict:
    """递归加密 dict 中所有 api_key 字段"""
    from services.crypto_service import encrypt
    result = {}
    for k, v in cfg.items():
        if k == "api_key" and isinstance(v, str) and v:
            result[k] = encrypt(v).decode("latin-1")  # 存为字符串
        elif isinstance(v, dict):
            result[k] = _encrypt_dict(v)
        else:
            result[k] = v
    return result


def _load_stored_ai_config(provider: str = "") -> dict:
    """从 settings 表读取已保存的 AI 配置（自动解密 api_key）

    - 多供应商模式: {"minimax": {"api_key":"...","model":"..."}, "deepseek": {...}}
    - 旧版单配置:   {"provider":"minimax","api_key":"...","model":"..."}
    - 指定 provider 时，只返回该供应商的配置
    """
    try:
        from database import query_one
        row = query_one("SELECT value FROM settings WHERE key = 'ai_config'")
        if row and row.get("value"):
            import json as _json
            cfg = _json.loads(row["value"])
            if isinstance(cfg, dict):
                cfg = _decrypt_dict(cfg)
                # 多供应商模式
                if provider and provider in cfg and isinstance(cfg[provider], dict):
                    return cfg[provider]
                if provider and "api_key" in cfg:
                    # 旧版单配置，直接返回
                    return cfg if cfg.get("provider") == provider else {}
                # 不指定 provider，返回原始数据
                return cfg
    except Exception:
        logger.debug("load_stored_ai_config: settings read failed")
    return {}


def save_stored_ai_config(config: dict) -> None:
    """保存 AI 配置到 settings 表（自动加密 api_key）"""
    from database import execute
    import json as _json
    encrypted = _encrypt_dict(config)
    execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('ai_config', ?)",
        (_json.dumps(encrypted, ensure_ascii=False),),
    )
