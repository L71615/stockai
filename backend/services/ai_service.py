"""StockAI — AI 模型服务

支持的供应商：MiniMax / Claude / OpenAI / OpenAI 兼容
"""

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from config import (
    AI_PROVIDER, CLAUDE_API_KEY, CLAUDE_MODEL,
    OPENAI_API_KEY, MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_BASE_URL,
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
        return response.content[0].text
    except ImportError:
        return "（请先安装 anthropic SDK: pip install anthropic）"
    except Exception as e:
        return f"（Claude API 调用失败: {e}）"


async def ai_chat(
    message: str,
    conversation_history: list[dict] = None,
    *,
    provider: str = "",
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    system_prompt: str = "",
) -> str:
    """统一的 AI 对话入口（多供应商调度）"""
    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": message})

    p = provider or AI_PROVIDER

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
